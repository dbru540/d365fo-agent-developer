#!/usr/bin/env bash
# Runs graphify export + stage for the 20 remaining Wave 1 custom packages.
# Writes per-package logs under .omx/logs/ and appends a running status line to .omx/graphify-wave1-progress.log.

set -u
cd "$(dirname "$0")/.."

REPO_ROOT="$(pwd)"
PACKAGES_ROOT="$REPO_ROOT/D365_repo/BabilouFinOps/PackagesLocalDirectory"
PROGRESS_LOG="$REPO_ROOT/.omx/graphify-wave1-progress.log"
LOGS_DIR="$REPO_ROOT/.omx/logs"
mkdir -p "$LOGS_DIR"

: > "$PROGRESS_LOG"

pkgs=(
  "BAB-ExportBFC"
  "BAB-ExportCreditTransfer"
  "BAB-ImportComptaetprovisionsdevente"
  "BAB-ImportPaymentConfirmation"
  "BAB-InterfacesKyriba"
  "BABAccountsReceivable"
  "BABAdministrationAndWorkFlow"
  "BABAssetStatusOrganization"
  "BABAssetVariationOrganization"
  "BABAuditTrail"
  "BABCountryRegionVendBankAccount"
  "BABFlexmindCockpitInterfaceExtension"
  "BABINT01Customer"
  "BABINT02CustomerTransaction"
  "BABINT04Infor"
  "BABLabels"
  "BABPaymentAdvice"
  "BABSuspendDimensionPerLegalEntity"
  "FLexmind-CockpitInterfaces"
  "FivefortyAssets"
)

export PYTHONPATH="$REPO_ROOT/src"

for pkg in "${pkgs[@]}"; do
  slug=$(echo "$pkg" | tr '[:upper:]' '[:lower:]')
  pkg_path="$PACKAGES_ROOT/$pkg"
  staging_dir="$REPO_ROOT/.omx/graphify-staging-$slug"
  run_dir="$REPO_ROOT/.omx/graphify-run-$slug"
  log_file="$LOGS_DIR/wave1-$slug.log"

  if [ ! -d "$pkg_path" ]; then
    echo "[SKIP] $pkg (missing at $pkg_path)" | tee -a "$PROGRESS_LOG"
    continue
  fi

  echo "[START] $pkg -> $slug" | tee -a "$PROGRESS_LOG"
  start_ts=$(date +%s)

  {
    python -m d365fo_agent.cli export-packageslocal-graphify \
      --packages-root "$pkg_path" \
      --output-dir "$staging_dir" \
    && python -m d365fo_agent.cli run-graphify-staging \
      --staging-dir "$staging_dir" \
      --output-dir "$run_dir"
  } > "$log_file" 2>&1

  rc=$?
  end_ts=$(date +%s)
  elapsed=$((end_ts - start_ts))

  if [ $rc -eq 0 ] && [ -f "$run_dir/graph.json" ]; then
    nodes=$(python -c "import json; d=json.load(open(r'$run_dir/graph.json', encoding='utf-8')); print(len(d.get('nodes', [])))" 2>/dev/null || echo "?")
    edges=$(python -c "import json; d=json.load(open(r'$run_dir/graph.json', encoding='utf-8')); print(len(d.get('links', [])))" 2>/dev/null || echo "?")
    echo "[DONE]  $pkg (${elapsed}s, nodes=$nodes, edges=$edges)" | tee -a "$PROGRESS_LOG"
  else
    echo "[FAIL]  $pkg (rc=$rc, ${elapsed}s) - see $log_file" | tee -a "$PROGRESS_LOG"
  fi
done

echo "[ALL DONE]" | tee -a "$PROGRESS_LOG"
