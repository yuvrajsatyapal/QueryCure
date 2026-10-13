#!/bin/zsh
S=${0:A:h}
cd /Users/yuvrajsatyapal/Desktop/Projects/QueryCure/backend
C="env PYTHONPATH=. uv run python $S/collect.py $S/real2.jsonl"
seq_() { seq $1 $2 | tr '\n' ' ' }
export D13_DELAY_MS=0.2; eval $C genuine_moderate $(seq_ 10000 10199)
export D13_DELAY_MS=0.2; eval $C genuine_moderate $(seq_ 10500 10699) --block-size 1
export D13_DELAY_MS=0.3; eval $C genuine_moderate $(seq_ 11000 11199)
export D13_DELAY_MS=0.3; eval $C genuine_moderate $(seq_ 11500 11699) --block-size 1
echo CAMPAIGN_DONE
