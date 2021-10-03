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
    --ack-deadline=60
gcloud pubsub subscriptions create $PUBSUB_OUTPUT_SUBSCRIPTION \
    --topic=${PUBSUB_OUTPUT_TOPIC} \
    --ack-deadline=60
```

create service account resources and download service account key

```
gcloud iam service-accounts create $WORKER_SERVICE_ACCOUNT \
    --description="gke and keda pubsub reader service account" \
    --display-name=$WORKER_SERVICE_ACCOUNT

gcloud projects add-iam-policy-binding $PROJECT \
    --member "serviceAccount:${WORKER_SERVICE_ACCOUNT}@${PROJECT}.iam.gserviceaccount.com" \
    --role "roles/pubsub.publisher"

gcloud projects add-iam-policy-binding $PROJECT \
    --member "serviceAccount:${WORKER_SERVICE_ACCOUNT}@${PROJECT}.iam.gserviceaccount.com" \
    --role "roles/pubsub.subscriber"

gcloud projects add-iam-policy-binding $PROJECT \
    --member "serviceAccount:${WORKER_SERVICE_ACCOUNT}@${PROJECT}.iam.gserviceaccount.com" \
    --role "roles/monitoring.viewer"

gcloud iam service-accounts add-iam-policy-binding \
    --role roles/iam.workloadIdentityUser \
    --member "serviceAccount:${PROJECT}.svc.id.goog[keda-pubsub/${WORKER_SERVICE_ACCOUNT}]" \
    ${WORKER_SERVICE_ACCOUNT}@${PROJECT}.iam.gserviceaccount.com

gcloud iam service-accounts keys create key-file.json \
    --iam-account=${WORKER_SERVICE_ACCOUNT}@${PROJECT}.iam.gserviceaccount.com
```

create base k8s namespace, service account and SA key secret (since KEDA doesn't yet support Workload Identity)

```
cat <<EOF > k8s/sa.yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: ${WORKER_SERVICE_ACCOUNT}
  namespace: keda-pubsub
EOF

kubectl apply -f k8s/namespace.yaml
kubectl apply -f k8s/sa.yaml

# this part doesn't work because workload identity isn't supported in KEDA yet
kubectl annotate serviceaccount \
    --namespace keda-pubsub ${WORKER_SERVICE_ACCOUNT} \
    iam.gke.io/gcp-service-account=${WORKER_SERVICE_ACCOUNT}@${PROJECT}.iam.gserviceaccount.com

kubectl create secret generic pubsub-secret \
  --from-file=GOOGLE_APPLICATION_CREDENTIALS=./key-file.json \
  --from-literal=PROJECT=$PROJECT \
  -n keda-pubsub
```


#### create worker image 

```
cd worker && pack build \
--builder gcr.io/buildpacks/builder:v1 \
--publish gcr.io/${PROJECT}/keda-pubsub-test-worker && cd ..
```

#### create K8s deployment

```
cat <<EOF > k8s/deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: keda-pubsub-worker
  namespace: keda-pubsub
spec:
  replicas: 1
  selector:
    matchLabels:
      app: keda-pubsub-worker
  template:
    metadata:
      labels:
        app: keda-pubsub-worker
    spec:
      volumes:
      - name: google-cloud-key
        secret:
          secretName: pubsub-secret
      containers:
      - name: worker
        image: gcr.io/${PROJECT}/keda-pubsub-test-worker
        volumeMounts:
        - name: google-cloud-key
          mountPath: /var/secrets/google
        env:
        - name: PROJECT
          valueFrom:
            secretKeyRef:
              name: pubsub-secret
              key: PROJECT
        - name: PUBSUB_INGEST_SUBSCRIPTION
          value: ${PUBSUB_INGEST_SUBSCRIPTION}
        - name: PUBSUB_OUTPUT_TOPIC
          value: ${PUBSUB_OUTPUT_TOPIC}
        - name: GOOGLE_APPLICATION_CREDENTIALS
          value: /var/secrets/google/GOOGLE_APPLICATION_CREDENTIALS
        - name: GOOGLE_APPLICATION_CREDENTIALS_JSON # used by KEDA
          valueFrom:
            secretKeyRef:
              name: pubsub-secret
              key: GOOGLE_APPLICATION_CREDENTIALS
      #serviceAccountName: ${WORKER_SERVICE_ACCOUNT}
EOF

kubectl apply -f k8s/deployment.yaml
```

#### set up KEDA

```
cat <<EOF > k8s/keda-pubsub-scaler.yaml
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: pubsub-scaledobject
  namespace: keda-pubsub
spec:
  scaleTargetRef:
    name: keda-pubsub-worker
  pollingInterval: 15  # Optional. Default: 30 seconds
  cooldownPeriod:  30 # Optional. Default: 300 seconds
  triggers:
  - type: gcp-pubsub
    metadata:
      subscriptionSize: "5"
      subscriptionName: ${PUBSUB_INGEST_SUBSCRIPTION} # Required
      credentialsFromEnv: GOOGLE_APPLICATION_CREDENTIALS_JSON # Required
      #credentialsFromEnv: GOOGLE_APPLICATION_CREDENTIALS # Required
EOF

kubectl apply -f k8s/keda-pubsub-scaler.yaml
```

#### send test messages to the ingest topic 

try this from a few different terminal sessions 

```
for i in {1..100}
do
   gcloud pubsub topics publish $PUBSUB_INGEST_TOPIC \
   --message=$(od -N 4 -t uL -An /dev/urandom | tr -d " ")
done
```

#### receive output topic messages

```
watch -n 2 gcloud alpha pubsub subscriptions pull $PUBSUB_OUTPUT_SUBSCRIPTION --auto-ack --limit 25
```

output:

```
$ gcloud alpha pubsub subscriptions pull $PUBSUB_OUTPUT_SUBSCRIPTION --auto-ack --limit 25
┌─────────────────────────────────────────────────────────────────────────────────────┬──────────────────┬──────────────┬────────────┬──────────────────┐
│                                         DATA                                        │    MESSAGE_ID    │ ORDERING_KEY │ ATTRIBUTES │ DELIVERY_ATTEMPT │
├─────────────────────────────────────────────────────────────────────────────────────┼──────────────────┼──────────────┼────────────┼──────────────────┤
│ 3533427344 is not a prime number - processed by keda-pubsub-worker-565ff4fffb-svhrg │ 3166664891990025 │              │            │                  │
│ 1770762633 is not a prime number - processed by keda-pubsub-worker-565ff4fffb-689bh │ 3166637726529058 │              │            │                  │
│ 3641977476 is not a prime number - processed by keda-pubsub-worker-565ff4fffb-d6sdp │ 3166636488685443 │              │            │                  │
└─────────────────────────────────────────────────────────────────────────────────────┴──────────────────┴──────────────┴────────────┴──────────────────┘
```