"""Train CleanConnect's real waste-image classifier from TrashNet.

First run:
    python train_model.py

The script downloads the 42.8 MB resized TrashNet archive automatically when
it is not already present, extracts the six labelled folders, creates a
stratified 80/20 hold-out split, trains a Random Forest, prints a classification
report, and saves the trained artifact used by Flask.

Dataset source: Gary Thung / Mindy Yang, Stanford CS229 TrashNet.
"""
import json
import os
import shutil
from datetime import datetime, timezone
import sys
import urllib.request
import zipfile
from collections import Counter

import joblib
import numpy as np
from PIL import Image
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, balanced_accuracy_score, classification_report, confusion_matrix, f1_score
from sklearn.model_selection import train_test_split

from models.waste_classifier import MODEL_PATH, extract_features

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATASET_DIR = os.path.join(BASE_DIR, "dataset", "dataset-resized")
LOCAL_DATASET_ARG = sys.argv[1] if len(sys.argv) > 1 else None
ARCHIVE_PATH = os.path.join(BASE_DIR, "dataset", "dataset-resized.zip")
MODEL_DIR = os.path.dirname(MODEL_PATH)
DATASET_URL = "https://huggingface.co/datasets/garythung/trashnet/resolve/main/dataset-resized.zip"

# TrashNet -> CleanConnect labels.
ALIASES = {
    "cardboard": "Cardboard",
    "glass": "Glass",
    "metal": "Metal",
    "paper": "Paper",
    "plastic": "Plastic",
    "trash": "Mixed Waste",
}
IMAGE_EXTS = {".jpg", ".jpeg", ".png"}


def download_dataset():
    global DATASET_DIR
    if LOCAL_DATASET_ARG:
        DATASET_DIR = os.path.abspath(LOCAL_DATASET_ARG)
        if not os.path.isdir(DATASET_DIR):
            raise FileNotFoundError(f"Local dataset folder not found: {DATASET_DIR}")
        print(f"Using local dataset: {DATASET_DIR}")
        return
    if os.path.isdir(DATASET_DIR):
        return
    os.makedirs(os.path.dirname(ARCHIVE_PATH), exist_ok=True)
    print("Downloading TrashNet dataset (about 42.8 MB)...")
    print(DATASET_URL)
    urllib.request.urlretrieve(DATASET_URL, ARCHIVE_PATH)
    print("Extracting dataset...")
    with zipfile.ZipFile(ARCHIVE_PATH, "r") as zf:
        zf.extractall(os.path.join(BASE_DIR, "dataset"))
    # Some archives extract directly to dataset-resized; keep this tolerant.
    if not os.path.isdir(DATASET_DIR):
        raise RuntimeError(f"Expected extracted dataset at {DATASET_DIR}")


def load_dataset():
    X, y, counts = [], [], Counter()
    for folder in sorted(os.listdir(DATASET_DIR)):
        label = ALIASES.get(folder.lower())
        folder_path = os.path.join(DATASET_DIR, folder)
        if not label or not os.path.isdir(folder_path):
            continue
        for filename in sorted(os.listdir(folder_path)):
            if os.path.splitext(filename)[1].lower() not in IMAGE_EXTS:
                continue
            path = os.path.join(folder_path, filename)
            try:
                with Image.open(path) as img:
                    X.append(extract_features(img))
                y.append(label)
                counts[label] += 1
            except Exception as exc:
                print(f"Skipping {path}: {exc}")
    if len(X) < 100 or len(set(y)) != 6:
        raise RuntimeError(
            "TrashNet was not loaded correctly. Expected all 6 classes and at least 100 images. "
            f"Found classes={sorted(set(y))}, images={len(X)}"
        )
    return np.asarray(X, dtype=np.float32), np.asarray(y), counts


def main():
    download_dataset()
    X, y, counts = load_dataset()
    print(f"Loaded {len(X)} labelled images.")
    print("Class counts:", dict(sorted(counts.items())))

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.20, random_state=42, stratify=y
    )

    model = RandomForestClassifier(
        n_estimators=400,
        class_weight="balanced",
        random_state=42,
        n_jobs=-1,
        min_samples_leaf=1,
    )
    print("Training Random Forest...")
    model.fit(X_train, y_train)

    predictions = model.predict(X_test)
    accuracy = float(accuracy_score(y_test, predictions))
    balanced_accuracy = float(balanced_accuracy_score(y_test, predictions))
    macro_f1 = float(f1_score(y_test, predictions, average="macro", zero_division=0))
    report = classification_report(y_test, predictions, zero_division=0)
    print("\n" + report)
    print(f"Hold-out test accuracy: {accuracy * 100:.2f}%")
    print(f"Balanced accuracy: {balanced_accuracy * 100:.2f}%")
    print(f"Macro F1: {macro_f1 * 100:.2f}%")

    os.makedirs(MODEL_DIR, exist_ok=True)
    bundle = {
        "model": model,
        "classes": list(model.classes_),
        "test_accuracy": accuracy,
        "balanced_accuracy": balanced_accuracy,
        "macro_f1": macro_f1,
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "n_classes": int(len(set(y))),
        "n_features": int(X.shape[1]),
        "n_train": int(len(X_train)),
        "n_test": int(len(X_test)),
        "dataset_name": "TrashNet (Gary Thung / Mindy Yang)",
        "dataset_url": DATASET_URL,
        "feature_version": 2,
    }
    joblib.dump(bundle, MODEL_PATH, compress=3)

    with open(os.path.join(MODEL_DIR, "training_report.txt"), "w", encoding="utf-8") as fh:
        fh.write("CleanConnect real ML training report\n")
        fh.write("Dataset: TrashNet (2527 images, six classes)\n")
        fh.write(f"Train images: {len(X_train)}\nTest images: {len(X_test)}\n")
        fh.write(f"Hold-out test accuracy: {accuracy * 100:.2f}%\n")
        fh.write(f"Balanced accuracy: {balanced_accuracy * 100:.2f}%\n")
        fh.write(f"Macro F1: {macro_f1 * 100:.2f}%\n")
        fh.write(f"Trained at (UTC): {bundle['trained_at']}\n\n")
        fh.write(report)
    with open(os.path.join(MODEL_DIR, "confusion_matrix.csv"), "w", encoding="utf-8") as fh:
        labels = list(model.classes_)
        matrix = confusion_matrix(y_test, predictions, labels=labels)
        fh.write("," + ",".join(labels) + "\n")
        for label, row in zip(labels, matrix):
            fh.write(label + "," + ",".join(map(str, row)) + "\n")

    model_card = {
        "project": "CleanConnect",
        "model": "RandomForestClassifier",
        "dataset": "TrashNet (Gary Thung / Mindy Yang)",
        "dataset_url": DATASET_URL,
        "classes": list(model.classes_),
        "images_total": int(len(X)),
        "images_train": int(len(X_train)),
        "images_test": int(len(X_test)),
        "accuracy": accuracy,
        "balanced_accuracy": balanced_accuracy,
        "macro_f1": macro_f1,
        "class_counts": dict(sorted(counts.items())),
        "trained_at_utc": bundle["trained_at"],
        "limitations": [
            "TrashNet is a small benchmark dataset and may not represent local lighting, backgrounds, or real-world waste mixtures.",
            "Random Forest predict_proba scores are not calibrated confidence estimates.",
            "Human review is recommended for low-scoring predictions.",
        ],
    }
    with open(os.path.join(MODEL_DIR, "model_card.json"), "w", encoding="utf-8") as fh:
        json.dump(model_card, fh, indent=2)

    print(f"\nREAL trained model saved to:\n{MODEL_PATH}")
    print("The Flask app will now use this model for uploaded images.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"\nTraining failed: {exc}")
        print("Check your internet connection and run 'python train_model.py' again.")
        sys.exit(1)
