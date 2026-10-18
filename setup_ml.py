"""One-command ML setup for CleanConnect.

Run:
    python setup_ml.py

This installs the ML dependencies, downloads TrashNet and trains the real
classifier. It does not create a demo/fixed-rule model.
"""
import subprocess
import sys

subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"])
subprocess.check_call([sys.executable, "train_model.py"])
print("\nML setup complete. Start the website with: python app.py")
