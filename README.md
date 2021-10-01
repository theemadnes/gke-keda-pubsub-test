# gke-keda-pubsub-test
The repo name says it all - just testing a sample autoscaled app for job processing. Uses GCP BuildPacks for image builds.

#### infra setup 

set env vars
```
export PROJECT=$(gcloud config get-value project) # or your preferred project
export GKE_REGION=us-central1 # or whatever you want to use 
export PUBSUB_INGEST_TOPIC=ingest-topic
export PUBSUB_OUTPUT_TOPIC=output-topic
export PUBSUB_INGEST_SUBSCRIPTION=ingest-subscription
export PUBSUB_OUTPUT_SUBSCRIPTION=output-subscription
export WORKER_SERVICE_ACCOUNT=worker-sa
export KEDA_SERVICE_ACCOUNT=keda-sa
```

create the GKE cluster
```
gcloud container clusters create keda-pubsub \
    --machine-type=e2-standard-4 \
    --num-nodes=1 \
    --region ${GKE_REGION} \
    --enable-stackdriver-kubernetes \
    --enable-ip-alias \
    --workload-pool=${PROJECT}.svc.id.goog \
    --release-channel rapid
```

deploy KEDA
```
kubectl apply -f https://github.com/kedacore/keda/releases/download/v2.4.0/keda-2.4.0.yaml
```

create the pubsub resources
```
gcloud pubsub topics create $PUBSUB_INGEST_TOPIC
gcloud pubsub topics create $PUBSUB_OUTPUT_TOPIC
gcloud pubsub subscriptions create $PUBSUB_INGEST_SUBSCRIPTION \
    --topic=${PUBSUB_INGEST_TOPIC} \
    --ack-deadline=600
gcloud pubsub subscriptions create $PUBSUB_OUTPUT_SUBSCRIPTION \
    --topic=${PUBSUB_OUTPUT_TOPIC} \
    --ack-deadline=60
```

#### create worker image 

```
cd worker && pack build \
--builder gcr.io/buildpacks/builder:v1 \
--publish gcr.io/${PROJECT}/keda-pubsub-test-worker && cd ..
```

#### send test messages to the ingest topic 

```
for i in {1..20}
do
   gcloud pubsub topics publish $PUBSUB_INGEST_TOPIC \
   --message=$(od -N 6 -t uL -An /dev/urandom | tr -d " ")
done
```

#### receive output topic messages

```
gcloud alpha pubsub subscriptions pull $PUBSUB_OUTPUT_SUBSCRIPTION --auto-ack --limit 50
```