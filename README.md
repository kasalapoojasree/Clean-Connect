# 🌿 CleanConnect

**Connect. Report. Clean. Transform.** - an AI-assisted Community Cleanliness Management System (CSE / AI & ML college project).

Citizens report garbage and cleanliness problems with a photo and location. An image-classification module suggests the waste type. Volunteers sign up for local activities. Administrators manage complaints, see them on a map and view analytics.

## Features
- Citizen registration / login (hashed passwords, sessions), user dashboard
- Complaint form with photo upload, validation, live AI preview, map location picker and unique IDs (`CC-2026-0001`)
- Complaint tracking with a 5-step progress tracker and status history
- "My Reports" with search and status/category filters
- Volunteer registration + admin volunteer list
- Separate admin login, dashboard, search/filter, status updates, delete
- Leaflet + OpenStreetMap map (marker size/colour = severity, dashed = resolved)
- Chart.js analytics (6 charts from real database data)
- Waste awareness page, friendly 404/500 pages, responsive Bootstrap 5 layout
- Optional demo data that can be loaded and removed in one click
- **ML Insights admin page** with model readiness, measured metrics, dataset class counts, model card and limitations
- Ranked top-3 predictions; low-scoring predictions are flagged for human review
- Machine-readable model card JSON, balanced accuracy, macro-F1, timestamped evaluation and confusion matrix
- `/api/health` endpoint for database/model readiness checks
- Automated smoke tests and safer first-run admin credential generation

## Technology stack
| Layer | Tools |
|---|---|
| Frontend | HTML5, CSS3, JavaScript, Bootstrap 5, Bootstrap Icons, Chart.js, Leaflet |
| Backend | Python, Flask |
| Database | SQLite (auto-created) |
| AI/ML | Pillow + NumPy feature extraction + scikit-learn Random Forest |
| Dataset | TrashNet (2,527 labelled waste images, six classes) |
| Maps | OpenStreetMap tiles (no API key) |

> Bootstrap, Chart.js and Leaflet load from public CDNs, and map tiles come from OpenStreetMap, so an internet connection is needed in the browser.

## Folder structure
```
CleanConnect/
├── app.py
├── train_model.py          Real supervised ML training script
├── setup_ml.py             Installs dependencies and trains the model
├── setup_ml.bat            Windows one-click training setup
├── requirements.txt
├── .env.example            Safe configuration template (copy values into environment)
├── .gitignore              Excludes secrets, databases, uploads and generated model artifacts
├── tests/test_smoke.py     Basic application and ML pipeline smoke tests
├── dataset/                TrashNet is downloaded here by train_model.py
├── models/
│   ├── waste_classifier.py Real model loader + inference
│   └── model/              waste_classifier.joblib is generated after training
├── templates/
├── static/
└── instance/
```

## Installation (Windows + VS Code)
```bash
cd CleanConnect
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python train_model.py
python app.py
```
Open **http://127.0.0.1:5000**.

### Easier Windows setup
Double-click **setup_ml.bat**. It installs the ML packages, downloads TrashNet, trains the model and creates `models/model/waste_classifier.joblib`.

## Admin account and secrets
On first run, CleanConnect generates a unique random administrator password and saves it to `instance/admin_credentials.txt` on the local machine. Read that file once, then delete it after safely storing the password. The file is ignored by Git. For predictable deployment configuration, set `CLEANCONNECT_ADMIN_USER` and `CLEANCONNECT_ADMIN_PASSWORD` as environment variables **before the first run**. If an admin already exists, changing the environment variable does not automatically change the existing password; use `python app.py reset-admin` to rotate it. Never commit real passwords, `.env` files, databases, uploaded photos, or model artifacts to a public repository. `CLEANCONNECT_DEBUG` defaults to off.

## How the REAL AI/ML classification works
1. The user selects a JPG/PNG image.
2. Flask validates and converts it to an RGB Pillow image.
3. `extract_features()` converts the image into a numeric feature vector using RGB/HSV histograms, channel statistics and edge-density features.
4. `train_model.py` uses the labelled TrashNet images and a stratified 80/20 train/test split.
5. A scikit-learn **RandomForestClassifier** learns the relationship between the image features and the six waste labels.
6. The trained model is saved as `models/model/waste_classifier.joblib`.
7. The upload endpoint `/api/classify` loads that saved model and calls `predict_proba()` on the uploaded image.
8. The returned class and confidence are stored with the complaint.

**There is no demo heuristic fallback anymore.** If the trained model is missing, the application reports that the model must be trained instead of pretending a fixed-rule prediction is AI.

### TrashNet labels
- Cardboard
- Glass
- Metal
- Paper
- Plastic
- Mixed Waste (TrashNet `trash`)

The training script writes `models/model/training_report.txt`, `models/model/confusion_matrix.csv`, and `models/model/model_card.json`. The evaluation includes hold-out accuracy, balanced accuracy, macro-F1, per-class precision/recall/F1, train/test counts, class counts, and training timestamp. The admin-only **ML Insights** page presents the saved evaluation evidence. These metrics are valid only for that split and dataset; do not describe them as guaranteed real-world performance.

### Prediction handling
The classifier returns its top three candidate classes. If the top Random Forest score is below 55%, CleanConnect marks the result for manual confirmation. This is a conservative workflow flag, not a calibrated probability threshold; the threshold should be validated on a separate real-world validation set before production use.

### Health check and tests
After installing requirements, run `python -m unittest discover -s tests -v`. Check model/database readiness at `http://127.0.0.1:5000/api/health`; it returns `200` when both are ready and `503` if the app is degraded. The ML Insights page is at `/admin/ml-insights` and requires administrator login.

## Important viva statement
Say: **"We trained a Random Forest classifier on the labelled TrashNet waste-image dataset. The uploaded image is transformed using the same feature-extraction pipeline and passed to the saved trained model for prediction."**

Do not quote an accuracy number until you run `python train_model.py` and use the accuracy printed by that run.

## Demo data
`python app.py seed` loads the existing demo database rows. Those rows can contain sample AI values and are explicitly marked DEMO; they are not ML predictions. A newly uploaded image is classified only by the trained model.

## Security notes
Password hashing (Werkzeug), session cookies (HttpOnly, SameSite), CSRF tokens on POST, parameterised SQL, upload validation, randomised image filenames, admin-only routes and login throttling are retained.

## Troubleshooting
- **"trained ML model is missing"**: run `python train_model.py`.
- **Training download fails**: check internet access, then run the command again.
- **Map/charts blank**: check browser internet access for the public CDNs.
- **Forgot admin password**: `python app.py reset-admin`; check the terminal or `instance/admin_credentials.txt` for the newly generated credential.
- **Health check says `not_trained`**: run `python train_model.py`, then restart the application.
- **ML Insights page shows no report**: confirm training completed and `models/model/model_card.json` exists.
- **Port 5000 in use**: close the other process or change the port.

## Viva architecture
```
TrashNet labelled images
        ↓
Feature extraction
        ↓
80/20 stratified split
        ↓
Random Forest training
        ↓
Saved waste_classifier.joblib
        ↓
User uploads image
        ↓
Same feature extraction
        ↓
Trained model prediction + confidence
        ↓
CleanConnect report / database
```

## Resume-ready project description
**CleanConnect — AI-powered Community Cleanliness Management System**  
Built a Flask-based civic reporting platform with citizen authentication, complaint tracking, volunteer coordination, geospatial visualization and administrative analytics. Developed a supervised waste-image classification pipeline using TrashNet, Pillow/NumPy feature extraction and scikit-learn Random Forest. Added top-3 predictions, low-score human-review flags, class-wise evaluation, balanced accuracy, macro-F1, confusion matrix, model card, health endpoint and smoke tests.  
**Important:** Add measured model metrics to your resume only after running training and saving the actual evaluation report. Do not claim a metric that you have not measured.

## Suggested next research upgrade
The current model is a classical ML baseline using engineered colour/texture features. A future experimental branch could compare it with a transfer-learning CNN (e.g. MobileNetV2) using a fixed train/validation/test protocol. Keep the current Random Forest as a baseline and report per-class metrics, inference latency and model size. Do not replace the current model until the comparison demonstrates a measurable improvement.
