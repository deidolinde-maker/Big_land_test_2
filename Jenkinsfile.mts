def pipeline
node {
  properties([pipelineTriggers([cron('TZ=Europe/Moscow\n30 0,5,11,14,17,20,22 * * *')])])
  checkout scm
  pipeline = load 'jenkins/brand_pipeline.groovy'
  pipeline.runBrand('mts')
}
