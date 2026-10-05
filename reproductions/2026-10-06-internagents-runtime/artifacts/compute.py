import csv, json
from pathlib import Path

rows = []
with open("data.csv", newline="", encoding="utf-8") as f:
    for r in csv.DictReader(f):
        rows.append((float(r["x"]), float(r["y"])))

n = len(rows)
ys = [y for _, y in rows]
y_mean = sum(ys) / n

se_linear = sum((y - (2 * x + 1)) ** 2 for x, y in rows)
se_mean = sum((y - y_mean) ** 2 for _, y in rows)

linear_mse = se_linear / n
mean_mse = se_mean / n

Path("result.json").write_text(
    json.dumps({"linear_mse": linear_mse, "mean_mse": mean_mse, "n": n}, ensure_ascii=False, indent=2) + "\n",
    encoding="utf-8",
)

print(f"n={n} y_mean={y_mean}")
print(f"linear_mse={linear_mse} mean_mse={mean_mse}")
print(f"sse_linear={se_linear} sse_mean={se_mean}")
