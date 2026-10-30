def runBrand(String fixedScope) {
  node {
    timestamps {
      def testFailure = null
      def testFile = fixedScope in ['mts_gpon_ab', 'mts_home_online_ab']
        ? 'mts_ab_tests/test_mts_ab.py'
        : 'big_landing_code.py'

      withCredentials([
        string(credentialsId: 'browser_proxy_creds', variable: 'BROWSER_PROXY'),
        string(credentialsId: 'telegram_proxy_url', variable: 'TELEGRAM_PROXY_URL'),
        string(credentialsId: 'telegram_proxy_auth_secret', variable: 'TELEGRAM_PROXY_AUTH_SECRET'),
        string(credentialsId: 'tg_proxy_creds_survarius', variable: 'TELEGRAM_PROXY_CREDS'),
      ]) {
        withEnv([
          "RUN_MODE=brand-oriented",
          "BRAND_SCOPE=${fixedScope}",
          "PROVIDER_SCOPE=${fixedScope}",
          "NOTIFY_MODE=twice_daily",
          "PYTHONUNBUFFERED=1",
          "PW_VIDEO_DIR=artifacts/videos",
          "SUMMARY_STATE_FILE=/var/lib/jenkins/shared/big_landing_test/summary_state.json",
          "ALERT_STATE_FILE=/var/lib/jenkins/shared/big_landing_test/alert_state.json",
          "PLAYWRIGHT_BROWSERS_PATH=/var/lib/jenkins/cache/ms-playwright",
          "PIP_CACHE_DIR=/var/lib/jenkins/cache/pip",
        ]) {
          try {
            stage('Checkout') {
              checkout scm
            }

            stage('Prepare Python') {
              sh '''
                set -e
                if [ ! -x .venv/bin/python ]; then
                  python3 -m venv .venv
                fi
                .venv/bin/python -m pip install --cache-dir "${PIP_CACHE_DIR}" -r requirements.txt
                .venv/bin/python -m playwright install chromium
              '''
            }

            stage("Run ${fixedScope}") {
              sh """
                set -e
                rm -rf allure-results allure-results-* || true
                mkdir -p allure-results
                .venv/bin/python -m pytest ${testFile} \\
                  --alluredir=allure-results \\
                  --timeout=600 -s \\
                  --service-mode=all \\
                  --browser=chromium \\
                  --blocking-profile=none \\
                  --run-mode=brand-oriented \\
                  --brand-scope=${fixedScope}
              """
            }
          } catch (err) {
            testFailure = err
            currentBuild.result = 'FAILURE'
          } finally {
            stage('Allure and notifications') {
              sh '''
                set +e
                mkdir -p allure-results
                export ALLURE_RESULTS_DIR="allure-results"
                export RUN_URL="${BUILD_URL}"
                export ALLURE_URL="${BUILD_URL}allure/"
                export TELEGRAM_ALERT_EVENTS_FILE="telegram_alert_events.jsonl"
                .venv/bin/python notify_from_allure.py || true
                if [ -s telegram_alert_message.txt ] && [ "$(cat telegram_alert_should_send.txt 2>/dev/null | tr -d '[:space:]')" = "1" ]; then
                  .venv/bin/python - <<'PY'
from pathlib import Path
from big_landing_code import send_telegram_alert
text = Path("telegram_alert_message.txt").read_text(encoding="utf-8").strip()
if text:
    send_telegram_alert(text, alert_type="step")
PY
                fi
                if [ -s telegram_message.txt ] && [ "$(cat telegram_should_send.txt 2>/dev/null | tr -d '[:space:]')" = "1" ]; then
                  .venv/bin/python - <<'PY'
from pathlib import Path
from big_landing_code import send_telegram_alert
text = Path("telegram_message.txt").read_text(encoding="utf-8").strip()
if text:
    send_telegram_alert(text, alert_type="summary")
PY
                fi
              '''
              try {
                allure includeProperties: false, jdk: '', results: [[path: 'allure-results']]
              } catch (ignored) {
                echo 'Allure publish skipped.'
              }
              archiveArtifacts artifacts: 'allure-results/**, artifacts/videos/**, telegram_message.txt, telegram_should_send.txt, telegram_alert_message.txt, telegram_alert_should_send.txt', allowEmptyArchive: true
            }
          }
        }
      }
      if (testFailure != null) {
        throw testFailure
      }
    }
  }
}

return this
