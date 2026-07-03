import pandas as pd

from process import OUT


KEY = ["sector", "leader", "follower"]


def z(s):
    s = s.fillna(0)
    return (s - s.mean()) / s.std(ddof=0) if s.std(ddof=0) else s * 0


def lag_part():
    df = pd.read_csv(OUT / "lag_corr_by_group" / "lead_edges.csv")
    df = df.rename(columns={"group": "sector", "lead": "leader", "follow": "follower", "lead_edge": "lag_diff"})
    return df.sort_values("lag_diff", ascending=False).drop_duplicates(KEY)[
        KEY + ["lag", "lag_corr", "lag_diff"]
    ].rename(columns={"lag": "best_lag"})


def residual_part():
    df = pd.read_csv(OUT / "residual_corr_by_group" / "residual_lead_edges.csv")
    df = df.rename(columns={"group": "sector", "lead": "leader", "follow": "follower"})
    return df.sort_values("residual_lead_edge", ascending=False).drop_duplicates(KEY)[
        KEY + ["residual_lag_corr", "residual_lead_edge"]
    ]


def rolling_part():
    df = pd.read_csv(OUT / "rolling_corr_by_group" / "rolling_lead_corr.csv")
    df["rolling_win"] = df["lead_strength"].gt(0)
    return df.groupby(KEY, as_index=False).agg(rolling_stability=("rolling_win", "mean"))


def granger_score(p):
    if p < 0.01:
        return 1.0
    if p < 0.05:
        return 0.7
    if p < 0.10:
        return 0.4
    return 0.0


def granger_part():
    df = pd.read_csv(OUT / "granger_by_group" / "granger_results.csv").dropna(subset=["p_value"])
    df = df.rename(columns={"leader_candidate": "leader", "follower_candidate": "follower"})
    df = df.loc[df.groupby(KEY)["p_value"].idxmin()].copy()
    df["granger_score"] = df["p_value"].map(granger_score)
    return df[KEY + ["lag", "p_value", "granger_score"]].rename(columns={"lag": "granger_lag", "p_value": "granger_p"})


def var_part():
    df = pd.read_csv(OUT / "var_by_group" / "var_coefficients.csv")
    df = df.rename(columns={"leader_candidate": "leader", "follower_candidate": "follower"})
    df = df[df["leader"] != df["follower"]].copy()
    df["var_score"] = ((df["is_var_significant"]) & (df["var_coefficient"] > 0)) * 1.0
    df.loc[(df["is_var_significant"]) & (df["var_coefficient"] < 0), "var_score"] = 0.5
    df["abs_coef"] = df["var_coefficient"].abs()
    df = df.sort_values(["var_score", "var_p_value", "abs_coef"], ascending=[False, True, False])
    return df.drop_duplicates(KEY)[KEY + ["var_coefficient", "var_p_value", "var_score"]].rename(
        columns={"var_coefficient": "var_coef", "var_p_value": "var_p"}
    )


def main():
    score = lag_part()
    for part in [residual_part(), rolling_part(), granger_part(), var_part()]:
        score = score.merge(part, on=KEY, how="outer")

    for col in ["lag_corr", "lag_diff", "residual_lag_corr", "residual_lead_edge", "rolling_stability", "granger_score", "var_score"]:
        score[col] = score[col].fillna(0)

    score["score"] = (
        0.25 * z(score["lag_diff"])
        + 0.20 * z(score["residual_lead_edge"])
        + 0.20 * z(score["rolling_stability"])
        + 0.20 * score["granger_score"]
        + 0.15 * score["var_score"]
    )

    cols = [
        "sector", "leader", "follower", "score", "best_lag", "lag_corr", "lag_diff",
        "residual_lag_corr", "rolling_stability", "granger_p", "var_coef", "var_p",
    ]
    out = OUT / "leading_score_by_group"
    out.mkdir(parents=True, exist_ok=True)
    score.sort_values(["sector", "score"], ascending=[True, False])[cols].to_csv(
        out / "leading_scores.csv", index=False, encoding="utf-8-sig"
    )
    print(f"Saved to {out / 'leading_scores.csv'}")


if __name__ == "__main__":
    main()
