"""Deterministic role fixtures, NOT model agents or research-paper replication."""
from math import isclose


def metrics(actual, predicted):
    n = len(actual)
    return {"mse": sum((a-p)**2 for a, p in zip(actual, predicted))/n,
            "mae": sum(abs(a-p) for a, p in zip(actual, predicted))/n}


def execute(store, task):
    role = task["role"]
    base = {"simulation": True, "role": role, "task_id": task["id"],
            "plan_version": task["version"], "direction": task["instruction"],
            "limitation": "角色为固定程序，未调用语言模型或检索论文。只处理 5 个合成数据点；自由文字方向只保存，不会自动编写新实验。"}
    if role == "researcher":
        y = [1, 3, 5, 7, 9]
        if task["scenario"] == "outlier":
            y[-1] += 6
        return {**base, "summary": "准备了 5 个可复算的数据点，用来演示组会如何改变下一轮输入。",
                "dataset": {"x": [0, 1, 2, 3, 4], "y": y},
                "scenario": task["scenario"], "source": "LabCouncil 自有固定合成数据；没有文献来源"}
    prior = store.dependency_artifact(task)
    if role == "executor":
        data = prior["body"]["dataset"]
        x, y = data["x"], data["y"]
        mx, my = sum(x)/len(x), sum(y)/len(y)
        slope = sum((a-mx)*(b-my) for a, b in zip(x, y))/sum((a-mx)**2 for a in x)
        intercept = my-slope*mx
        prediction = [slope*a+intercept for a in x]
        score = metrics(y, prediction)
        baseline = metrics(y, [my]*len(y))
        return {**base, "summary": f"在这 5 个点上，拟合直线的平均平方误差是 {score['mse']:.3g}；只猜平均值是 {baseline['mse']:.3g}。这不是独立测试集表现。",
                "dataset_id": prior["id"], "dataset_sha256": prior["sha256"],
                "slope": slope, "intercept": intercept, "prediction": prediction,
                "metrics": score, "baseline": baseline,
                "method": "普通最小二乘；在同一批样本上拟合和评分，只用于流程演示"}
    if role == "reviewer":
        computed = prior["body"]
        original = store.artifact(computed["dataset_id"])
        import json
        data = json.loads(original["body"])["dataset"]
        x, y = data["x"], data["y"]
        n, sx, sy = len(x), sum(x), sum(y)
        # Separate sum-form solution, then independently reconstruct errors.
        slope = (n*sum(a*b for a, b in zip(x, y))-sx*sy)/(n*sum(a*a for a in x)-sx*sx)
        intercept = (sy-slope*sx)/n
        prediction = [intercept+slope*a for a in x]
        mse = sum((prediction[i]-y[i])**2 for i in range(n))/n
        mae = sum(abs(prediction[i]-y[i]) for i in range(n))/n
        baseline_mse = sum((b-sy/n)**2 for b in y)/n
        checks = {
            "dataset_hash": original["sha256"] == computed["dataset_sha256"],
            "coefficients": isclose(slope, computed["slope"], abs_tol=1e-10) and isclose(intercept, computed["intercept"], abs_tol=1e-10),
            "predictions": len(prediction) == len(computed["prediction"]) and all(isclose(a, b, abs_tol=1e-10) for a, b in zip(prediction, computed["prediction"])),
            "mse": isclose(mse, computed["metrics"]["mse"], abs_tol=1e-10),
            "mae": isclose(mae, computed["metrics"]["mae"], abs_tol=1e-10),
            "baseline": isclose(baseline_mse, computed["baseline"]["mse"], abs_tol=1e-10)}
        passed = all(checks.values())
        return {**base, "summary": ("复算对上了这批数据、系数和误差。" if passed else "复算发现不一致，请检查证据。") + "这只核对算术，不能说明方法能推广到真实问题。",
                "verified": passed, "checks": checks, "executor_artifact_id": prior["id"],
                "executor_sha256": prior["sha256"], "dataset_id": original["id"],
                "independent_result": {"slope": slope, "intercept": intercept, "mse": mse, "mae": mae, "baseline_mse": baseline_mse}}
    raise ValueError("Unknown simulation role")
