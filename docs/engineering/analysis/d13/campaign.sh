#!/bin/zsh
set -u
S=${0:A:h}
cd /Users/yuvrajsatyapal/Desktop/Projects/QueryCure/backend
C="env PYTHONPATH=. uv run python $S/collect.py $S/real.jsonl"
seq_() { seq $1 $2 | tr '\n' ' ' }
eval $C neutral_scan $(seq_ 1000 1299)
eval $C neutral_scan $(seq_ 2000 2299) --block-size 1
eval $C neutral_pk $(seq_ 3000 3199)
eval $C neutral_pk $(seq_ 3500 3699) --block-size 1
export D13_DELAY_MS=0.7; eval $C genuine_moderate $(seq_ 4000 4149)
export D13_DELAY_MS=0.7; eval $C genuine_moderate $(seq_ 4500 4649) --block-size 1
export D13_DELAY_MS=1.7; eval $C genuine_moderate $(seq_ 5000 5099)
export D13_DELAY_MS=1.7; eval $C genuine_moderate $(seq_ 5500 5599) --block-size 1
eval $C genuine_large $(seq_ 6000 6049)
eval $C genuine_large $(seq_ 6500 6549) --block-size 1
eval $C neutral_scan $(seq_ 7000 7149) --load
eval $C neutral_scan $(seq_ 7500 7649) --block-size 1 --load
export D13_DELAY_MS=0.7; eval $C genuine_moderate $(seq_ 8000 8099) --load
export D13_DELAY_MS=0.7; eval $C genuine_moderate $(seq_ 8500 8599) --block-size 1 --load
eval $C neutral_scan $(seq_ 9000 9149) --block-size 2
echo CAMPAIGN_DONE
