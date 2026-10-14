这条台账是 2026-09-17 真正产生写入的那次 --apply（created=8 / updated=4）。
⚠ 其中 created 行的 target_id(37-44) 是【当次】的 id：
  之后我按队长要求做过一次 --rollback 实测 + 一次重跑 --apply，
  最终落库的 id 是 62-69（见 checkin-merge-latest.jsonl 与 docs/audit/checkin-merge-report.md）。
本文件只作"写入那一次"的证据留档，不要拿它去回滚（回滚用 latest）。
