
import pandas as pd
import joblib

from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import classification_report, accuracy_score

# Load the labelled training dataset
data = pd.read_csv("complaint_training_data.csv")

data["description"] = data["description"].fillna("").str.strip()
data["department"] = data["department"].fillna("").str.strip()

data = data[
    (data["description"] != "") &
    (data["department"] != "")
]

print("Training examples:", len(data))
print("\nExamples per department:")
print(data["department"].value_counts())

# Keep a separate test set to evaluate the model
if data["department"].nunique() < 2:
    raise ValueError("Training data must contain at least two departments.")

try:
    
   X_train, X_test, y_train, y_test = train_test_split(
    data["description"],
    data["department"],
    test_size=0.25,
    random_state=42,
    stratify=data["department"]
)

except ValueError:
    raise ValueError(
        "Add more labelled examples to each department before training. "
        "The dataset is too small for a stratified split."
    )

# Build the machine-learning pipeline
model = Pipeline([
    ("tfidf", TfidfVectorizer(
        lowercase=True,
        ngram_range=(1, 2),
        sublinear_tf=True
    )),
    ("classifier", LogisticRegression(
        max_iter=1000,
        class_weight="balanced",
        random_state=42
    ))
])

# Train and evaluate
model.fit(X_train, y_train)
predictions = model.predict(X_test)

print("\nTest accuracy:", round(accuracy_score(y_test, predictions), 3))
print("\nEvaluation report:")
print(classification_report(
    y_test,
    predictions,
    zero_division=0
))

# Retrain on all available examples after evaluation
model.fit(data["description"], data["department"])
joblib.dump(model, "civicfix_department_model.joblib")

print("\nModel saved as civicfix_department_model.joblib")
print("\nSample predictions:")
samples = [
    "Garbage is overflowing near the bus stop",
    "A huge pothole is damaging vehicles",
    "The streetlight is broken",
    "There is no water supply",
    "Sewage is overflowing from the manhole",
    "Rainwater is flooding the road"
]

for description in samples:
    prediction = model.predict([description])[0]
    print(f"{description} -> {prediction}")
