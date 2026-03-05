#!/usr/bin/env python3
"""
CloudEMS Seq2Point NILM Model Trainer — v1.22.0

Traint per-apparaat Seq2Point regressiemodellen en exporteert ze als ONNX.
De getrainde modellen worden gebruikt door de _NilmEnhancer in coordinator.py
om het vermogen van actieve apparaten nauwkeuriger te schatten.

Gebruik:
    pip install numpy torch onnx scikit-learn pandas
    python train_nilm_models.py --data_dir ./nilm_data --output_dir ./nilm_models

Dataset-formaat (CSV per huis, kolom per apparaat):
    timestamp,grid,refrigerator,washing_machine,dishwasher,...
    1380000000,1234.5,142.3,0.0,0.0,...

Publieke datasets:
    REDD:    http://redd.csail.mit.edu/
    UK-DALE: https://jack-kelly.com/data/
    ECO:     https://www.vs.inf.ethz.ch/res/show.html?what=eco-data

Copyright © 2025 CloudEMS — https://cloudems.eu
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
_LOGGER = logging.getLogger(__name__)

# ── Apparaat-configuratie ──────────────────────────────────────────────────────
# Elk apparaat heeft een eigen activatiedrempel (W) voor het aanmaken van trainingsvensters.
APPLIANCE_CONFIG: Dict[str, Dict] = {
    "refrigerator":    {"on_threshold": 50,   "max_power": 400},
    "washing_machine": {"on_threshold": 200,  "max_power": 3000},
    "dishwasher":      {"on_threshold": 200,  "max_power": 3000},
    "dryer":           {"on_threshold": 300,  "max_power": 3500},
    "boiler":          {"on_threshold": 200,  "max_power": 4000},
    "cv_boiler":       {"on_threshold": 100,  "max_power": 3000},
    "kettle":          {"on_threshold": 1000, "max_power": 3500},
    "microwave":       {"on_threshold": 200,  "max_power": 2000},
    "oven":            {"on_threshold": 300,  "max_power": 4000},
    "television":      {"on_threshold": 20,   "max_power": 400},
    "computer":        {"on_threshold": 50,   "max_power": 600},
    "heat_pump":       {"on_threshold": 200,  "max_power": 5000},
    "ev_charger":      {"on_threshold": 500,  "max_power": 25000},
    "light":           {"on_threshold": 5,    "max_power": 500},
    "electric_heater": {"on_threshold": 200,  "max_power": 4000},
}

SEQ2P_WIN    = 599   # venstergrootte: moet overeenkomen met _SEQ2P_WIN in coordinator.py
STRIDE       = 10    # stap tussen vensters (samples)
BATCH_SIZE   = 256
EPOCHS       = 50
LR           = 1e-3
VALID_SPLIT  = 0.15
RANDOM_SEED  = 42


def load_csv_dataset(data_dir: Path) -> Dict[str, "np.ndarray"]:
    """Laad alle CSV-bestanden en geef dict {kolom_naam: 1D array} terug."""
    import numpy as np
    import pandas as pd

    all_data: Dict[str, List] = {}
    csv_files = list(data_dir.glob("*.csv")) + list(data_dir.glob("**/*.csv"))

    if not csv_files:
        _LOGGER.error("Geen CSV-bestanden gevonden in %s", data_dir)
        sys.exit(1)

    for csv_file in sorted(csv_files):
        try:
            df = pd.read_csv(csv_file, index_col=0)
            df = df.fillna(0.0).clip(lower=0.0)
            _LOGGER.info("Geladen: %s (%d rijen, %d kolommen)", csv_file.name, len(df), len(df.columns))
            for col in df.columns:
                col_lower = col.lower().replace(" ", "_")
                if col_lower not in all_data:
                    all_data[col_lower] = []
                all_data[col_lower].append(df[col].values.astype(np.float32))
        except Exception as exc:
            _LOGGER.warning("Overgeslagen %s: %s", csv_file.name, exc)

    # Concateneer per kanaal
    result = {}
    for key, arrays in all_data.items():
        result[key] = np.concatenate(arrays)

    # Rapporteer wat gevonden is
    for key in sorted(result.keys()):
        _LOGGER.info("  Kanaal %-30s: %d samples (max=%.0fW)", key, len(result[key]), result[key].max())

    return result


def make_windows(
    mains: "np.ndarray",
    target: "np.ndarray",
    window: int,
    stride: int,
    on_threshold: float,
    max_power: float,
) -> Tuple["np.ndarray", "np.ndarray"]:
    """
    Maak (X, y) trainingsvensters via sliding window.

    X: genormaliseerd mainssignaal [N, window]
    y: doelvermogen op het middelpunt [N, 1], genormaliseerd 0..1
    """
    import numpy as np

    n = min(len(mains), len(target))
    half = window // 2
    xs, ys = [], []

    for i in range(half, n - half, stride):
        win_mains = mains[i - half: i + half + 1]
        if len(win_mains) < window:
            continue
        y_val = float(target[i])

        # Balanceer: ~ 50% aan, 50% uit
        if y_val < on_threshold and len(xs) > 0 and len(xs) % 2 == 0:
            continue

        # Normaliseer X via z-score
        mu    = win_mains.mean()
        sigma = win_mains.std() + 1e-6
        x_norm = (win_mains - mu) / sigma

        # Normaliseer y op [0, 1] t.o.v. max_power
        y_norm = np.clip(y_val / max_power, 0.0, 1.0)

        xs.append(x_norm.astype(np.float32))
        ys.append(np.float32(y_norm))

    if not xs:
        return np.empty((0, window), dtype=np.float32), np.empty((0,), dtype=np.float32)

    return np.array(xs, dtype=np.float32), np.array(ys, dtype=np.float32).reshape(-1, 1)


def build_model(window: int) -> "torch.nn.Module":
    """
    Seq2Point architectuur: Conv1D encoder + FC decoder.

    Input:  [batch, window]  (z-score normalized mains)
    Output: [batch, 1]       (normalized appliance power 0..1)

    Architectuur gebaseerd op:
      Zhang et al. (2018) "Sequence-to-point learning with neural networks for
      non-intrusive load monitoring" AAAI-18.
    """
    import torch.nn as nn

    class Seq2Point(nn.Module):
        def __init__(self, win: int) -> None:
            super().__init__()
            self.encoder = nn.Sequential(
                nn.Conv1d(1, 30, kernel_size=10, stride=1, padding=4),
                nn.ReLU(),
                nn.Conv1d(30, 30, kernel_size=8, stride=1, padding=3),
                nn.ReLU(),
                nn.Conv1d(30, 40, kernel_size=6, stride=1, padding=2),
                nn.ReLU(),
                nn.Conv1d(40, 50, kernel_size=5, stride=1, padding=2),
                nn.ReLU(),
                nn.Conv1d(50, 50, kernel_size=5, stride=1, padding=2),
                nn.ReLU(),
                nn.Flatten(),
            )
            # Bereken output-dimensie van encoder
            import torch
            dummy = torch.zeros(1, 1, win)
            enc_out = self.encoder(dummy).shape[1]

            self.decoder = nn.Sequential(
                nn.Linear(enc_out, 1024),
                nn.ReLU(),
                nn.Dropout(0.1),
                nn.Linear(1024, 1),
                nn.Sigmoid(),   # output 0..1
            )

        def forward(self, x):
            x = x.unsqueeze(1)  # [B, 1, W]
            return self.decoder(self.encoder(x))

    return Seq2Point(window)


def train_appliance(
    mains: "np.ndarray",
    target: "np.ndarray",
    appliance: str,
    config: dict,
    output_dir: Path,
) -> bool:
    """Train één apparaatmodel en sla op als ONNX. Geeft True terug bij succes."""
    try:
        import numpy as np
        import torch
        import torch.nn as nn
        from torch.utils.data import DataLoader, TensorDataset, random_split
    except ImportError as exc:
        _LOGGER.error("PyTorch niet gevonden: %s — installeer met: pip install torch", exc)
        return False

    torch.manual_seed(RANDOM_SEED)
    np.random.seed(RANDOM_SEED)

    on_thr   = config["on_threshold"]
    max_pw   = config["max_power"]

    _LOGGER.info("▶ Trainen: %s (on_threshold=%.0fW, max_power=%.0fW)", appliance, on_thr, max_pw)

    X, y = make_windows(mains, target, SEQ2P_WIN, STRIDE, on_thr, max_pw)
    if len(X) < 100:
        _LOGGER.warning("  Te weinig trainingsvensters (%d) voor %s — overgeslagen", len(X), appliance)
        return False

    _LOGGER.info("  Trainingsvensters: %d", len(X))

    dataset   = TensorDataset(torch.from_numpy(X), torch.from_numpy(y))
    val_size  = max(1, int(len(dataset) * VALID_SPLIT))
    train_size = len(dataset) - val_size
    train_ds, val_ds = random_split(dataset, [train_size, val_size])

    train_dl = DataLoader(train_ds, batch_size=BATCH_SIZE, shuffle=True,  num_workers=0)
    val_dl   = DataLoader(val_ds,   batch_size=BATCH_SIZE, shuffle=False, num_workers=0)

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model  = build_model(SEQ2P_WIN).to(device)

    optimizer = torch.optim.Adam(model.parameters(), lr=LR)
    scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(optimizer, patience=5, factor=0.5)
    criterion = nn.MSELoss()

    best_val_loss = float("inf")
    best_state    = None

    for epoch in range(1, EPOCHS + 1):
        # Train
        model.train()
        train_loss = 0.0
        for xb, yb in train_dl:
            xb, yb = xb.to(device), yb.to(device)
            optimizer.zero_grad()
            pred = model(xb)
            loss = criterion(pred, yb)
            loss.backward()
            optimizer.step()
            train_loss += loss.item() * len(xb)
        train_loss /= train_size

        # Valideer
        model.eval()
        val_loss = 0.0
        with torch.no_grad():
            for xb, yb in val_dl:
                xb, yb = xb.to(device), yb.to(device)
                pred = model(xb)
                val_loss += criterion(pred, yb).item() * len(xb)
        val_loss /= val_size
        scheduler.step(val_loss)

        if epoch % 10 == 0 or epoch == 1:
            _LOGGER.info("  Epoch %3d/%d: train_loss=%.5f val_loss=%.5f", epoch, EPOCHS, train_loss, val_loss)

        if val_loss < best_val_loss:
            best_val_loss = val_loss
            best_state    = {k: v.cpu().clone() for k, v in model.state_dict().items()}

    # Laad beste gewichten
    model.load_state_dict(best_state)
    model.eval()

    # Exporteer als ONNX
    # BELANGRIJK: het model verwacht genormaliseerde input [1, SEQ2P_WIN]
    # en geeft genormaliseerde output [1, 1] terug (0..1).
    # De coordinator de-normaliseert: pred_w = output * max_power
    # Sla max_power op als metadata zodat de coordinator weet hoe te de-normaliseren.
    try:
        import torch.onnx
        import onnx
        from onnx import helper, TensorProto

        dummy_input = torch.zeros(1, SEQ2P_WIN, dtype=torch.float32).to(device)
        onnx_path   = output_dir / f"{appliance}.onnx"

        torch.onnx.export(
            model,
            dummy_input,
            str(onnx_path),
            input_names  = ["X"],
            output_names = ["Y"],
            dynamic_axes = {"X": {0: "batch"}, "Y": {0: "batch"}},
            opset_version= 17,
        )

        # Voeg max_power toe als custom metadata in het ONNX-model
        onnx_model = onnx.load(str(onnx_path))
        meta = onnx_model.metadata_props.add()
        meta.key   = "max_power_w"
        meta.value = str(max_pw)
        meta2 = onnx_model.metadata_props.add()
        meta2.key   = "appliance"
        meta2.value = appliance
        meta3 = onnx_model.metadata_props.add()
        meta3.key   = "cloudems_version"
        meta3.value = "1.22.0"
        onnx.save(onnx_model, str(onnx_path))

        _LOGGER.info("  ✓ Opgeslagen: %s (val_loss=%.5f)", onnx_path, best_val_loss)
        return True

    except ImportError as exc:
        _LOGGER.error("  ONNX export mislukt: %s — installeer met: pip install onnx", exc)
        return False
    except Exception as exc:
        _LOGGER.error("  ONNX export fout: %s", exc)
        return False


def synthetic_dataset(appliance: str, config: dict, n_hours: int = 500) -> Tuple["np.ndarray", "np.ndarray"]:
    """
    Genereer synthetische trainingsdata als er geen echte dataset beschikbaar is.
    Simuleert een typisch dagpatroon voor het apparaat.
    """
    import numpy as np

    rng    = np.random.default_rng(RANDOM_SEED)
    n      = n_hours * 360  # 1 sample per 10s
    mains  = np.zeros(n, dtype=np.float32)
    target = np.zeros(n, dtype=np.float32)

    on_pw  = (config["on_threshold"] + config["max_power"]) / 2
    noise  = on_pw * 0.05

    # Simuleer typisch gebruikspatroon (uur-gebaseerd)
    on_hours = {
        "refrigerator":    list(range(0, 24)),         # altijd
        "washing_machine": [7, 8, 9, 18, 19, 20],
        "dishwasher":      [20, 21, 22],
        "kettle":          [7, 8, 12, 15, 18],
        "microwave":       [7, 12, 18, 19],
        "oven":            [12, 13, 18, 19, 20],
        "television":      [18, 19, 20, 21, 22],
        "boiler":          [6, 7, 8, 18, 19, 20, 21],
        "heat_pump":       list(range(0, 24)),
        "dryer":           [9, 10, 11, 14, 15],
        "ev_charger":      [22, 23, 0, 1, 2, 3, 4, 5],
    }.get(appliance, list(range(24)))

    base_mains = 600.0  # W basisverbruik huis
    mains[:] = base_mains + rng.normal(0, 30, n).astype(np.float32)

    samples_per_hour = 360
    for i in range(n):
        hour = (i // samples_per_hour) % 24
        if hour in on_hours:
            # Toestel aan/uit cycli
            cycle = (i // (samples_per_hour // 4)) % 2
            if appliance == "refrigerator":
                cycle = (i // (samples_per_hour * 2)) % 3 == 0  # 33% duty cycle
            if cycle:
                pw = on_pw + rng.normal(0, noise)
                target[i] = max(0.0, float(pw))
                mains[i] += target[i]

    return mains, target


def main() -> None:
    parser = argparse.ArgumentParser(description="CloudEMS NILM Seq2Point Model Trainer")
    parser.add_argument("--data_dir",   type=Path, default=None,
                        help="Map met CSV-datasets (REDD/UK-DALE formaat). "
                             "Weglaten = synthetische data gebruiken.")
    parser.add_argument("--output_dir", type=Path, default=Path("nilm_models"),
                        help="Uitvoermap voor ONNX-modellen (standaard: ./nilm_models)")
    parser.add_argument("--appliances", nargs="+", default=list(APPLIANCE_CONFIG.keys()),
                        help="Welke apparaten trainen (standaard: alle)")
    parser.add_argument("--epochs",     type=int, default=EPOCHS,
                        help=f"Trainingsepochs (standaard: {EPOCHS})")
    parser.add_argument("--synthetic",  action="store_true",
                        help="Forceer synthetische data ook als data_dir opgegeven")
    args = parser.parse_args()

    global EPOCHS
    EPOCHS = args.epochs

    args.output_dir.mkdir(parents=True, exist_ok=True)
    _LOGGER.info("CloudEMS NILM Trainer v1.22.0")
    _LOGGER.info("Output: %s", args.output_dir.resolve())

    # Laad dataset als opgegeven
    real_data: Dict[str, "np.ndarray"] = {}
    if args.data_dir and args.data_dir.exists() and not args.synthetic:
        _LOGGER.info("Laad dataset van %s", args.data_dir)
        real_data = load_csv_dataset(args.data_dir)

        # Zoek mainssignaal
        mains_candidates = ["aggregate", "mains", "grid", "main", "site"]
        mains_key = next((k for k in mains_candidates if k in real_data), None)
        if mains_key is None:
            mains_key = next(iter(real_data))
            _LOGGER.warning("Geen 'aggregate'/'mains' kolom gevonden — %s wordt als netsignaal gebruikt", mains_key)
        mains = real_data[mains_key]
        _LOGGER.info("Netsignaal: %s (%d samples = %.0f uur)", mains_key, len(mains), len(mains) / 360)
    else:
        mains = None
        _LOGGER.info("Geen dataset opgegeven — synthetische trainingsdata wordt gebruikt")

    # Train elk apparaat
    results = {}
    for appliance in args.appliances:
        if appliance not in APPLIANCE_CONFIG:
            _LOGGER.warning("Onbekend apparaattype: %s — overgeslagen", appliance)
            continue

        config = APPLIANCE_CONFIG[appliance]

        # Zoek doelsignaal in dataset, of gebruik synthetisch
        if mains is not None and appliance in real_data:
            target = real_data[appliance]
            _LOGGER.info("Echte data voor %s gevonden", appliance)
        else:
            _LOGGER.info("Synthetische data voor %s", appliance)
            mains_synth, target = synthetic_dataset(appliance, config)
            if mains is None:
                mains_use = mains_synth
            else:
                n = min(len(mains), len(target))
                mains_use = mains[:n]
                target    = target[:n]
            mains_use = mains_synth if mains is None else mains_use

        n = min(len(mains if mains is not None else mains_use), len(target))
        m = mains[:n] if mains is not None else mains_use[:n]
        t = target[:n]

        success = train_appliance(m, t, appliance, config, args.output_dir)
        results[appliance] = "✓" if success else "✗"

    # Samenvatting
    _LOGGER.info("\n=== Trainingsresultaten ===")
    for appliance, status in results.items():
        _LOGGER.info("  %s  %s", status, appliance)

    # Sla ook max_power metadata op in JSON (handig voor coordinator)
    meta_path = args.output_dir / "models_meta.json"
    meta = {
        a: {"max_power_w": APPLIANCE_CONFIG[a]["max_power"]}
        for a in results if results[a] == "✓"
    }
    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2)
    _LOGGER.info("Metadata opgeslagen: %s", meta_path)


if __name__ == "__main__":
    main()
