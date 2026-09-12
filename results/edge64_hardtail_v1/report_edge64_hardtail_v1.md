# Edge64 hard-tail isolation

{
  "residual_cases": 4693,
  "budget_survival": [
    {
      "budget": 0.5,
      "survivors": 1542
    },
    {
      "budget": 1.0,
      "survivors": 741
    },
    {
      "budget": 2.0,
      "survivors": 383
    },
    {
      "budget": 5.0,
      "survivors": 146
    }
  ],
  "tournament": {
    "corpus_size": 146,
    "methods": [
      {
        "method": "compressed",
        "solved": 0,
        "rate": 0.0
      },
      {
        "method": "hybrid",
        "solved": 65,
        "rate": 0.4452054794520548
      },
      {
        "method": "branch",
        "solved": 76,
        "rate": 0.5205479452054794
      },
      {
        "method": "diff",
        "solved": 15,
        "rate": 0.10273972602739725
      },
      {
        "method": "tension",
        "solved": 58,
        "rate": 0.3972602739726027
      }
    ],
    "greedy_portfolio": [
      {
        "method": "branch",
        "newly_solved": 76,
        "cumulative_solved": 76
      },
      {
        "method": "hybrid",
        "newly_solved": 26,
        "cumulative_solved": 102
      },
      {
        "method": "tension",
        "newly_solved": 14,
        "cumulative_solved": 116
      },
      {
        "method": "diff",
        "newly_solved": 4,
        "cumulative_solved": 120
      }
    ],
    "top1_coverage": 0.821917808219178,
    "uncovered_after_all": 26
  },
  "post_portfolio_robust_hard": 24,
  "weighted_projection": {
    "universe_cases": 10040677,
    "weighted_robust_hard_rate": 0.0020339236002375823,
    "weighted_projected_robust_hard_cases": 20422,
    "stratum_details": [
      {
        "stratum": "three_branch|both_ge4|middle_even|terminal_min_ge3|balanced_le2",
        "universe_cases": 148368,
        "pilot_cases": 92,
        "robust_hard_cases": 3,
        "estimated_rate": 0.03260869565217391,
        "universe_weight": 0.014776692846508259,
        "projected_robust_cases": 4838
      },
      {
        "stratum": "three_branch|both_ge4|middle_even|terminal_min_ge3|moderate_3_8",
        "universe_cases": 316264,
        "pilot_cases": 82,
        "robust_hard_cases": 1,
        "estimated_rate": 0.012195121951219513,
        "universe_weight": 0.03149827446894268,
        "projected_robust_cases": 3857
      },
      {
        "stratum": "three_branch|both_ge4|middle_even|terminal_min_ge3|unbalanced_ge9",
        "universe_cases": 463152,
        "pilot_cases": 62,
        "robust_hard_cases": 0,
        "estimated_rate": 0.0,
        "universe_weight": 0.04612756689613658,
        "projected_robust_cases": 0
      },
      {
        "stratum": "three_branch|both_ge4|middle_even|terminal_min_le2|balanced_le2",
        "universe_cases": 177776,
        "pilot_cases": 63,
        "robust_hard_cases": 0,
        "estimated_rate": 0.0,
        "universe_weight": 0.017705579016235658,
        "projected_robust_cases": 0
      },
      {
        "stratum": "three_branch|both_ge4|middle_even|terminal_min_le2|moderate_3_8",
        "universe_cases": 400000,
        "pilot_cases": 67,
        "robust_hard_cases": 0,
        "estimated_rate": 0.0,
        "universe_weight": 0.03983795116604189,
        "projected_robust_cases": 0
      },
      {
        "stratum": "three_branch|both_ge4|middle_even|terminal_min_le2|unbalanced_ge9",
        "universe_cases": 882280,
        "pilot_cases": 26,
        "robust_hard_cases": 0,
        "estimated_rate": 0.0,
        "universe_weight": 0.0878705688869386,
        "projected_robust_cases": 0
      },
      {
        "stratum": "three_branch|both_ge4|middle_odd|terminal_min_ge3|balanced_le2",
        "universe_cases": 164164,
        "pilot_cases": 83,
        "robust_hard_cases": 0,
        "estimated_rate": 0.0,
        "universe_weight": 0.016349893538055254,
        "projected_robust_cases": 0
      },
      {
        "stratum": "three_branch|both_ge4|middle_odd|terminal_min_ge3|moderate_3_8",
        "universe_cases": 353056,
        "pilot_cases": 82,
        "robust_hard_cases": 0,
        "estimated_rate": 0.0,
        "universe_weight": 0.03516256921719522,
        "projected_robust_cases": 0
      },
      {
        "stratum": "three_branch|both_ge4|middle_odd|terminal_min_ge3|unbalanced_ge9",
        "universe_cases": 535260,
        "pilot_cases": 37,
        "robust_hard_cases": 0,
        "estimated_rate": 0.0,
        "universe_weight": 0.05330915435283896,
        "projected_robust_cases": 0
      },
      {
        "stratum": "three_branch|both_ge4|middle_odd|terminal_min_le2|balanced_le2",
        "universe_cases": 191646,
        "pilot_cases": 76,
        "robust_hard_cases": 0,
        "estimated_rate": 0.0,
        "universe_weight": 0.01908695997291816,
        "projected_robust_cases": 0
      },
      {
        "stratum": "three_branch|both_ge4|middle_odd|terminal_min_le2|moderate_3_8",
        "universe_cases": 433158,
        "pilot_cases": 51,
        "robust_hard_cases": 0,
        "estimated_rate": 0.0,
        "universe_weight": 0.04314031812795093,
        "projected_robust_cases": 0
      },
      {
        "stratum": "three_branch|both_ge4|middle_odd|terminal_min_le2|unbalanced_ge9",
        "universe_cases": 982828,
        "pilot_cases": 27,
        "robust_hard_cases": 0,
        "estimated_rate": 0.0,
        "universe_weight": 0.09788463467154655,
        "projected_robust_cases": 0
      },
      {
        "stratum": "three_branch|both_short_le3|middle_even|terminal_min_ge3|balanced_le2",
        "universe_cases": 15197,
        "pilot_cases": 146,
        "robust_hard_cases": 0,
        "estimated_rate": 0.0,
        "universe_weight": 0.0015135433596758466,
        "projected_robust_cases": 0
      },
      {
        "stratum": "three_branch|both_short_le3|middle_even|terminal_min_ge3|moderate_3_8",
        "universe_cases": 33890,
        "pilot_cases": 135,
        "robust_hard_cases": 0,
        "estimated_rate": 0.0,
        "universe_weight": 0.0033752704125428992,
        "projected_robust_cases": 0
      },
      {
        "stratum": "three_branch|both_short_le3|middle_even|terminal_min_ge3|unbalanced_ge9",
        "universe_cases": 97710,
        "pilot_cases": 99,
        "robust_hard_cases": 1,
        "estimated_rate": 0.010101010101010102,
        "universe_weight": 0.009731415521084884,
        "projected_robust_cases": 987
      },
      {
        "stratum": "three_branch|both_short_le3|middle_even|terminal_min_le2|balanced_le2",
        "universe_cases": 8478,
        "pilot_cases": 40,
        "robust_hard_cases": 0,
        "estimated_rate": 0.0,
        "universe_weight": 0.0008443653749642579,
        "projected_robust_cases": 0
      },
      {
        "stratum": "three_branch|both_short_le3|middle_even|terminal_min_le2|moderate_3_8",
        "universe_cases": 19498,
        "pilot_cases": 56,
        "robust_hard_cases": 0,
        "estimated_rate": 0.0,
        "universe_weight": 0.001941900929588712,
        "projected_robust_cases": 0
      },
      {
        "stratum": "three_branch|both_short_le3|middle_even|terminal_min_le2|unbalanced_ge9",
        "universe_cases": 90878,
        "pilot_cases": 77,
        "robust_hard_cases": 0,
        "estimated_rate": 0.0,
        "universe_weight": 0.009050983315168888,
        "projected_robust_cases": 0
      },
      {
        "stratum": "three_branch|both_short_le3|middle_odd|terminal_min_ge3|balanced_le2",
        "universe_cases": 15184,
        "pilot_cases": 149,
        "robust_hard_cases": 1,
        "estimated_rate": 0.006711409395973154,
        "universe_weight": 0.0015122486262629502,
        "projected_robust_cases": 102
      },
      {
        "stratum": "three_branch|both_short_le3|middle_odd|terminal_min_ge3|moderate_3_8",
        "universe_cases": 36056,
        "pilot_cases": 129,
        "robust_hard_cases": 1,
        "estimated_rate": 0.007751937984496124,
        "universe_weight": 0.003590992918107016,
        "projected_robust_cases": 280
      },
      {
        "stratum": "three_branch|both_short_le3|middle_odd|terminal_min_ge3|unbalanced_ge9",
        "universe_cases": 107360,
        "pilot_cases": 127,
        "robust_hard_cases": 2,
        "estimated_rate": 0.015748031496062992,
        "universe_weight": 0.010692506092965643,
        "projected_robust_cases": 1691
      },
      {
        "stratum": "three_branch|both_short_le3|middle_odd|terminal_min_le2|balanced_le2",
        "universe_cases": 8331,
        "pilot_cases": 56,
        "robust_hard_cases": 0,
        "estimated_rate": 0.0,
        "universe_weight": 0.0008297249279107375,
        "projected_robust_cases": 0
      },
      {
        "stratum": "three_branch|both_short_le3|middle_odd|terminal_min_le2|moderate_3_8",
        "universe_cases": 20241,
        "pilot_cases": 48,
        "robust_hard_cases": 0,
        "estimated_rate": 0.0,
        "universe_weight": 0.002015899923879635,
        "projected_robust_cases": 0
      },
      {
        "stratum": "three_branch|both_short_le3|middle_odd|terminal_min_le2|unbalanced_ge9",
        "universe_cases": 96883,
        "pilot_cases": 71,
        "robust_hard_cases": 0,
        "estimated_rate": 0.0,
        "universe_weight": 0.009649050557049092,
        "projected_robust_cases": 0
      },
      {
        "stratum": "three_branch|one_short_le3|middle_even|terminal_min_ge3|balanced_le2",
        "universe_cases": 107342,
        "pilot_cases": 116,
        "robust_hard_cases": 1,
        "estimated_rate": 0.008620689655172414,
        "universe_weight": 0.010690713385163171,
        "projected_robust_cases": 925
      },
      {
        "stratum": "three_branch|one_short_le3|middle_even|terminal_min_ge3|moderate_3_8",
        "universe_cases": 241070,
        "pilot_cases": 91,
        "robust_hard_cases": 0,
        "estimated_rate": 0.0,
        "universe_weight": 0.024009337218994297,
        "projected_robust_cases": 0
      },
      {
        "stratum": "three_branch|one_short_le3|middle_even|terminal_min_ge3|unbalanced_ge9",
        "universe_cases": 488098,
        "pilot_cases": 49,
        "robust_hard_cases": 0,
        "estimated_rate": 0.0,
        "universe_weight": 0.04861206072060679,
        "projected_robust_cases": 0
      },
      {
        "stratum": "three_branch|one_short_le3|middle_even|terminal_min_le2|balanced_le2",
        "universe_cases": 90639,
        "pilot_cases": 80,
        "robust_hard_cases": 0,
        "estimated_rate": 0.0,
        "universe_weight": 0.009027180139347177,
        "projected_robust_cases": 0
      },
      {
        "stratum": "three_branch|one_short_le3|middle_even|terminal_min_le2|moderate_3_8",
        "universe_cases": 211142,
        "pilot_cases": 79,
        "robust_hard_cases": 0,
        "estimated_rate": 0.0,
        "universe_weight": 0.021028661712751043,
        "projected_robust_cases": 0
      },
      {
        "stratum": "three_branch|one_short_le3|middle_even|terminal_min_le2|unbalanced_ge9",
        "universe_cases": 657650,
        "pilot_cases": 53,
        "robust_hard_cases": 0,
        "estimated_rate": 0.0,
        "universe_weight": 0.06549857146086863,
        "projected_robust_cases": 0
      },
      {
        "stratum": "three_branch|one_short_le3|middle_odd|terminal_min_ge3|balanced_le2",
        "universe_cases": 117130,
        "pilot_cases": 98,
        "robust_hard_cases": 1,
        "estimated_rate": 0.01020408163265306,
        "universe_weight": 0.011665548050196217,
        "projected_robust_cases": 1195
      },
      {
        "stratum": "three_branch|one_short_le3|middle_odd|terminal_min_ge3|moderate_3_8",
        "universe_cases": 262262,
        "pilot_cases": 90,
        "robust_hard_cases": 1,
        "estimated_rate": 0.011111111111111112,
        "universe_weight": 0.026119951871771196,
        "projected_robust_cases": 2914
      },
      {
        "stratum": "three_branch|one_short_le3|middle_odd|terminal_min_ge3|unbalanced_ge9",
        "universe_cases": 547118,
        "pilot_cases": 63,
        "robust_hard_cases": 0,
        "estimated_rate": 0.0,
        "universe_weight": 0.05449015041515627,
        "projected_robust_cases": 0
      },
      {
        "stratum": "three_branch|one_short_le3|middle_odd|terminal_min_le2|balanced_le2",
        "universe_cases": 96265,
        "pilot_cases": 77,
        "robust_hard_cases": 0,
        "estimated_rate": 0.0,
        "universe_weight": 0.009587500922497556,
        "projected_robust_cases": 0
      },
      {
        "stratum": "three_branch|one_short_le3|middle_odd|terminal_min_le2|moderate_3_8",
        "universe_cases": 223652,
        "pilot_cases": 67,
        "robust_hard_cases": 0,
        "estimated_rate": 0.0,
        "universe_weight": 0.022274593635469003,
        "projected_robust_cases": 0
      },
      {
        "stratum": "three_branch|one_short_le3|middle_odd|terminal_min_le2|unbalanced_ge9",
        "universe_cases": 714350,
        "pilot_cases": 35,
        "robust_hard_cases": 0,
        "estimated_rate": 0.0,
        "universe_weight": 0.07114560103865507,
        "projected_robust_cases": 0
      },
      {
        "stratum": "two_branch|long_ge9|terminal_min_ge3|balanced_le2",
        "universe_cases": 12528,
        "pilot_cases": 47,
        "robust_hard_cases": 0,
        "estimated_rate": 0.0,
        "universe_weight": 0.001247724630520432,
        "projected_robust_cases": 0
      },
      {
        "stratum": "two_branch|long_ge9|terminal_min_ge3|moderate_3_8",
        "universe_cases": 29529,
        "pilot_cases": 76,
        "robust_hard_cases": 1,
        "estimated_rate": 0.013157894736842105,
        "universe_weight": 0.0029409371499551275,
        "projected_robust_cases": 389
      },
      {
        "stratum": "two_branch|long_ge9|terminal_min_ge3|unbalanced_ge9",
        "universe_cases": 85035,
        "pilot_cases": 73,
        "robust_hard_cases": 0,
        "estimated_rate": 0.0,
        "universe_weight": 0.00846905044351093,
        "projected_robust_cases": 0
      },
      {
        "stratum": "two_branch|long_ge9|terminal_min_le2|balanced_le2",
        "universe_cases": 17268,
        "pilot_cases": 65,
        "robust_hard_cases": 0,
        "estimated_rate": 0.0,
        "universe_weight": 0.0017198043518380285,
        "projected_robust_cases": 0
      },
      {
        "stratum": "two_branch|long_ge9|terminal_min_le2|moderate_3_8",
        "universe_cases": 40947,
        "pilot_cases": 75,
        "robust_hard_cases": 0,
        "estimated_rate": 0.0,
        "universe_weight": 0.004078111465989793,
        "projected_robust_cases": 0
      },
      {
        "stratum": "two_branch|long_ge9|terminal_min_le2|unbalanced_ge9",
        "universe_cases": 162273,
        "pilot_cases": 57,
        "robust_hard_cases": 0,
        "estimated_rate": 0.0,
        "universe_weight": 0.016161559623917788,
        "projected_robust_cases": 0
      },
      {
        "stratum": "two_branch|medium_4_8|terminal_min_ge3|balanced_le2",
        "universe_cases": 7008,
        "pilot_cases": 134,
        "robust_hard_cases": 0,
        "estimated_rate": 0.0,
        "universe_weight": 0.000697960904429054,
        "projected_robust_cases": 0
      },
      {
        "stratum": "two_branch|medium_4_8|terminal_min_ge3|moderate_3_8",
        "universe_cases": 15998,
        "pilot_cases": 142,
        "robust_hard_cases": 1,
        "estimated_rate": 0.007042253521126761,
        "universe_weight": 0.0015933188568858455,
        "projected_robust_cases": 113
      },
      {
        "stratum": "two_branch|medium_4_8|terminal_min_ge3|unbalanced_ge9",
        "universe_cases": 65470,
        "pilot_cases": 116,
        "robust_hard_cases": 2,
        "estimated_rate": 0.017241379310344827,
        "universe_weight": 0.006520476657101907,
        "projected_robust_cases": 1129
      },
      {
        "stratum": "two_branch|medium_4_8|terminal_min_le2|balanced_le2",
        "universe_cases": 5956,
        "pilot_cases": 96,
        "robust_hard_cases": 0,
        "estimated_rate": 0.0,
        "universe_weight": 0.0005931870928623638,
        "projected_robust_cases": 0
      },
      {
        "stratum": "two_branch|medium_4_8|terminal_min_le2|moderate_3_8",
        "universe_cases": 13691,
        "pilot_cases": 85,
        "robust_hard_cases": 1,
        "estimated_rate": 0.011764705882352941,
        "universe_weight": 0.001363553473535699,
        "projected_robust_cases": 161
      },
      {
        "stratum": "two_branch|medium_4_8|terminal_min_le2|unbalanced_ge9",
        "universe_cases": 81798,
        "pilot_cases": 64,
        "robust_hard_cases": 1,
        "estimated_rate": 0.015625,
        "universe_weight": 0.008146661823699736,
        "projected_robust_cases": 1278
      },
      {
        "stratum": "two_branch|short_le3|terminal_min_ge3|balanced_le2",
        "universe_cases": 4832,
        "pilot_cases": 275,
        "robust_hard_cases": 2,
        "estimated_rate": 0.007272727272727273,
        "universe_weight": 0.000481242450085786,
        "projected_robust_cases": 35
      },
      {
        "stratum": "two_branch|short_le3|terminal_min_ge3|moderate_3_8",
        "universe_cases": 12248,
        "pilot_cases": 268,
        "robust_hard_cases": 3,
        "estimated_rate": 0.011194029850746268,
        "universe_weight": 0.0012198380647042027,
        "projected_robust_cases": 137
      },
      {
        "stratum": "two_branch|short_le3|terminal_min_ge3|unbalanced_ge9",
        "universe_cases": 56045,
        "pilot_cases": 143,
        "robust_hard_cases": 1,
        "estimated_rate": 0.006993006993006993,
        "universe_weight": 0.005581794932752044,
        "projected_robust_cases": 392
      },
      {
        "stratum": "two_branch|short_le3|terminal_min_le2|balanced_le2",
        "universe_cases": 3723,
        "pilot_cases": 79,
        "robust_hard_cases": 0,
        "estimated_rate": 0.0,
        "universe_weight": 0.0003707917304779349,
        "projected_robust_cases": 0
      },
      {
        "stratum": "two_branch|short_le3|terminal_min_le2|moderate_3_8",
        "universe_cases": 9499,
        "pilot_cases": 76,
        "robust_hard_cases": 0,
        "estimated_rate": 0.0,
        "universe_weight": 0.0009460517453155798,
        "projected_robust_cases": 0
      },
      {
        "stratum": "two_branch|short_le3|terminal_min_le2|unbalanced_ge9",
        "universe_cases": 62453,
        "pilot_cases": 43,
        "robust_hard_cases": 0,
        "estimated_rate": 0.0,
        "universe_weight": 0.006219998910432035,
        "projected_robust_cases": 0
      }
    ],
    "note": "Post-portfolio projection uses pilot stratum conditional rates; it is planning telemetry, not a confidence interval."
  },
  "high_budget_probe": {
    "input": 24,
    "solved": 22,
    "unresolved": 2
  },
  "classification": "ROBUST_HARD_TAIL"
}

All strategy experiments reuse the frozen 4,693-case residual manifest. No canonical case-generation rule or edge63 log was modified.

## Matched edge63 control

A deterministic 50,000-case edge63 control used the same hardware, solver
version, and `compressed -> diff -> tension` cascade with a 0.25-second budget
per tier:

```text
edge63 Tier0 survivors = 1,414 / 50,000 = 2.828%
edge63 Tier1 survivors = 1,238 / 50,000 = 2.476%
edge63 Tier2 survivors =   550 / 50,000 = 1.100%
```

The corresponding edge64 baseline pilot had a 2.3465% bounded Tier2 residual
rate, so the matched edge64 tail is about **2.13x** the edge63 control tail at
this budget. Both controls were independently certificate-verified with zero
errors. This is a matched empirical comparison, not an exhaustive hardness
theorem.

The combined edge64 audit rechecked **9,452** solved result rows from the
budget ladder, strategy tournament, portfolio, and high-budget probe, covering
**4,691** unique cases, with zero verification errors. Two cases remain
`UNRESOLVED_HIGH_BUDGET` after the 30-second probe.

On the 146-case tournament corpus, the greedy portfolio coverage was:

```text
branch                         76 / 146 = 52.05%
branch + hybrid               102 / 146 = 69.86%
branch + hybrid + tension     116 / 146 = 79.45%
branch + hybrid + tension
  + diff                      120 / 146 = 82.19%
```
