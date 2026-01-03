import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
from sklearn.model_selection import train_test_split
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_squared_error, r2_score
import os

# Paths
training_data_path = os.path.join("data", "processed", "training_data.parquet")

# Load data
df = pd.read_parquet(training_data_path)
print("Loaded training data:", df.shape)

# --- EDA ---
print("\nData sample:")
print(df.head())
print("\nData description:")
print(df.describe())
print("\nMissing values:")
print(df.isnull().sum())

# Correlation heatmap
plt.figure(figsize=(10, 6))
sns.heatmap(df.corr(numeric_only=True), annot=True, fmt=".2f", cmap="coolwarm")
plt.title("Feature Correlation Heatmap")
plt.tight_layout()
plt.savefig("eda_correlation_heatmap.png")
plt.close()

# --- Simple Model Training Example ---

# Predict 'mid' price as a regression target (example)
# Exclude all timestamp and non-numeric columns
numeric_cols = df.select_dtypes(include=["number"]).columns.tolist()
features = [col for col in numeric_cols if col != "mid"]
X = df[features]
y = df["mid"]

X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

model = RandomForestRegressor(n_estimators=100, random_state=42)
model.fit(X_train, y_train)

preds = model.predict(X_test)
#rmse = mean_squared_error(y_test, preds, squared=True)
rmse = mean_squared_error(y_test, preds) ** 0.5
r2 = r2_score(y_test, preds)

print(f"\nRandomForestRegressor RMSE: {rmse:.4f}")
print(f"RandomForestRegressor R^2: {r2:.4f}")
