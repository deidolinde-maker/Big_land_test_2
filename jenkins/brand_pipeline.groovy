def runBrand(String fixedScope) {
  timestamps {
      def testFailure = null
      def testFile = "scenarios/${fixedScope}.py"

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
          "SUMMARY_STATE_FILE=/var/lib/jenkins/shared/big_land_test_2/summary_${fixedScope}.json",
          "ALERT_STATE_FILE=/var/lib/jenkins/shared/big_land_test_2/alert_${fixedScope}.json",
          "PLAYWRIGHT_BROWSERS_PATH=/var/lib/jenkins/cache/ms-playwright",
          "PIP_CACHE_DIR=/var/lib/jenkins/cache/pip",
          "VENV_DIR=/var/lib/jenkins/cache/big_land_test_2/venv_${fixedScope}",
        ]) {
          try {
            stage('Checkout') {
              checkout scm
            }

            stage('Prepare Python') {
              sh '''
                set -e
                mkdir -p "${PIP_CACHE_DIR}" "${PLAYWRIGHT_BROWSERS_PATH}" "$(dirname "${VENV_DIR}")"
                if [ ! -x "${VENV_DIR}/bin/python" ]; then
                  python3 -m venv "${VENV_DIR}"
                fi
                "${VENV_DIR}/bin/python" -m pip install \
                  --cache-dir "${PIP_CACHE_DIR}" \
                  --prefer-binary \
                  -r requirements.txt
                "${VENV_DIR}/bin/python" -m playwright install chromium
              '''
            }

            stage("Run ${fixedScope}") {
              sh """
                set -e
                rm -rf allure-results allure-results-* || true
                mkdir -p allure-results
                "${VENV_DIR}/bin/python" -m pytest ${testFile} \\
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
                "${VENV_DIR}/bin/python" notify_from_allure.py || true
                if [ -s telegram_alert_message.txt ] && [ "$(cat telegram_alert_should_send.txt 2>/dev/null | tr -d '[:space:]')" = "1" ]; then
                  "${VENV_DIR}/bin/python" - <<'PY'
from pathlib import Path
from notification_transport import send_telegram_alert
text = Path("telegram_alert_message.txt").read_text(encoding="utf-8").strip()
if text:
    send_telegram_alert(text, alert_type="step")
PY
                fi
                if [ -s telegram_message.txt ] && [ "$(cat telegram_should_send.txt 2>/dev/null | tr -d '[:space:]')" = "1" ]; then
                  "${VENV_DIR}/bin/python" - <<'PY'
from pathlib import Path
from notification_transport import send_telegram_alert
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

return this
