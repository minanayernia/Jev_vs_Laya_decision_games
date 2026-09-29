#!/usr/bin/env bash
# Full experiment plan: single-shot, history, and control conditions for all six games.
#
#   bash experiments/run_plan.sh            # everything
#   bash experiments/run_plan.sh p1         # only runs whose name starts with p1 (p1, p1r, p2, ...)
#
# Every run is results/<game>/<PLAN>_<name>/; the console output of all runs goes to results/<PLAN>.log.
# A failed run is logged and the plan continues. 53 runs; measured: ~$0.06 in Jev tokens, ~23 min.

cd "$(dirname "$0")/.." || exit 1
PY=.venv/bin/python
PLAN="plan_$(date +%Y%m%d-%H%M)"
LOG="results/$PLAN.log"
FILTER="${1:-}"
mkdir -p results
failed=()

run() {  # run <name> <condition> <args...>
  local name=$1 condition=$2; shift 2
  [[ -n "$FILTER" && "$name" != "$FILTER"* ]] && return
  echo "=== $(date +%H:%M:%S) $name ($condition): $*" | tee -a "$LOG"
  if ! $PY experiments/run_tournament.py --experiment-id "${PLAN}_$name" --condition "$condition" "$@" \
       >>"$LOG" 2> >(grep -v -E "Warning|warn\(|return Agent|Fetching" >>"$LOG"); then
    echo "    FAILED: $name" | tee -a "$LOG"; failed+=("$name")
  fi
}

BC=(--game beauty_contest --players jev laya random random --grid-step 5)

# --- Phase 1: single-shot (no history) --------------------------------------------------------
run p1_pd          oneshot --mode one-shot --game prisoners_dilemma --rounds 20
run p1_mp          oneshot --mode one-shot --game matching_pennies  --rounds 20
run p1_rps         oneshot --mode one-shot --game rps               --rounds 20
run p1_ug_play     oneshot --mode one-shot --game ultimatum         --rounds 20
run p1_ug_sweep    oneshot --mode one-shot --game ultimatum --ultimatum-mode sweep --rounds 33
run p1_bc          oneshot --mode one-shot "${BC[@]}" --rounds 30
run p1_mh3         oneshot --mode one-shot --game monty_hall --doors 3  --rounds 200
run p1_mh10        oneshot --mode one-shot --game monty_hall --doors 10 --rounds 100
run p1_pd_t4       oneshot_payoff_3-0-4-1  --mode one-shot --game prisoners_dilemma --payoffs 3,0,4,1  --rounds 10
run p1_pd_t10      oneshot_payoff_3-0-10-1 --mode one-shot --game prisoners_dilemma --payoffs 3,0,10,1 --rounds 10

# --- Phase 1 control: same, options listed in reverse order (position bias) --------------------
run p1r_pd         oneshot_reversed --option-order reversed --mode one-shot --game prisoners_dilemma --rounds 10
run p1r_mp         oneshot_reversed --option-order reversed --mode one-shot --game matching_pennies  --rounds 10
run p1r_rps        oneshot_reversed --option-order reversed --mode one-shot --game rps               --rounds 10
run p1r_ug_play    oneshot_reversed --option-order reversed --mode one-shot --game ultimatum         --rounds 10
run p1r_ug_sweep   oneshot_reversed --option-order reversed --mode one-shot --game ultimatum --ultimatum-mode sweep --rounds 22
run p1r_bc         oneshot_reversed --option-order reversed --mode one-shot "${BC[@]}" --rounds 30
run p1r_mh3        oneshot_reversed --option-order reversed --mode one-shot --game monty_hall --doors 3 --rounds 100

# --- Phase 2: with history (last 5 rounds shown) ------------------------------------------------
run p2_pd          history --game prisoners_dilemma --rounds 50
run p2_mp          history --game matching_pennies  --rounds 50
run p2_rps         history --game rps               --rounds 50
run p2_rps_strat   history_strategic --prompt strategic --game rps --rounds 50
run p2_ug_play     history --game ultimatum         --rounds 30
for seed in 1 2 3; do
  run p2_bc_s$seed history "${BC[@]}" --rounds 20 --seed $seed
done
run p2_mh3         history --game monty_hall --doors 3 --rounds 100
run p2_pd_t4       history_payoff_3-0-4-1  --game prisoners_dilemma --payoffs 3,0,4,1  --rounds 50
run p2_pd_t10      history_payoff_3-0-10-1 --game prisoners_dilemma --payoffs 3,0,10,1 --rounds 50

# --- Phase 2 control: history + reversed options -------------------------------------------------
run p2r_pd         history_reversed --option-order reversed --game prisoners_dilemma --rounds 50
run p2r_mp         history_reversed --option-order reversed --game matching_pennies  --rounds 50
run p2r_rps        history_reversed --option-order reversed --game rps               --rounds 50

# --- Phase 2: known-strategy opponents -----------------------------------------------------------
for m in jev laya; do
  run p2f_pd_${m}_vs_defect    vs_fixed --game prisoners_dilemma --players $m fixed:DEFECT    --rounds 30
  run p2f_pd_${m}_vs_cooperate vs_fixed --game prisoners_dilemma --players $m fixed:COOPERATE --rounds 30
  run p2f_rps_${m}_vs_rock     vs_fixed --game rps               --players $m fixed:ROCK      --rounds 30
  run p2f_mp_${m}_vs_heads     vs_fixed --game matching_pennies  --players $m fixed:HEADS     --rounds 30
done

# --- Phase 2: vs a random opponent (the seeds give real repetitions) ------------------------------
for m in jev laya; do
  for seed in 1 2 3; do
    run p2x_rps_${m}_s$seed vs_random --game rps              --players $m random --rounds 50 --seed $seed
    run p2x_mp_${m}_s$seed  vs_random --game matching_pennies --players $m random --rounds 50 --seed $seed
  done
done

# --- Phase 2: self-play ---------------------------------------------------------------------------
run p2s_pd_jev     selfplay --game prisoners_dilemma --players jev jev   --rounds 50
run p2s_pd_laya    selfplay --game prisoners_dilemma --players laya laya --rounds 50

echo "=== $(date +%H:%M:%S) done: $PLAN  failed: ${#failed[@]} ${failed[*]}" | tee -a "$LOG"
