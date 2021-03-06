from concurrent.futures import TimeoutError
from google.cloud import pubsub_v1
import os
import socket
import math

# TODO(developer)
project_id = os.environ.get('PROJECT')
subscription_id = os.environ.get('PUBSUB_INGEST_SUBSCRIPTION')
# Number of seconds the subscriber should listen for messages
timeout = None #60.0 # how long to wait for new messages before exiting
output_topic_id = os.environ.get('PUBSUB_OUTPUT_TOPIC')

subscriber = pubsub_v1.SubscriberClient()
# The `subscription_path` method creates a fully qualified identifier
# in the form `projects/{project_id}/subscriptions/{subscription_id}`
subscription_path = subscriber.subscription_path(project_id, subscription_id)

publisher = pubsub_v1.PublisherClient()
# The `topic_path` method creates a fully qualified identifier
# in the form `projects/{project_id}/topics/{topic_id}`
publish_topic_path = publisher.topic_path(project_id, output_topic_id)

# function to check if a number is prime
def is_prime(n):
    if n == 2:
        return True
    if n % 2 == 0 or n <= 1:
        return False

    sqr = int(math.sqrt(n)) + 1

    for divisor in range(3, sqr, 2):
        if n % divisor == 0:
            return False
    return True


def callback(message: pubsub_v1.subscriber.message.Message) -> None:

    # determine if input value is prime number
    # code sample from https://www.programiz.com/python-programming/examples/prime-number

    print(message)
    num = int(message.data)

    # check if flag is True
    if is_prime(num):
        print(num, "is a prime number")
        data = f"{num} is a prime number - processed by {socket.gethostname()}"
        data = data.encode("utf-8")
        future = publisher.publish(publish_topic_path, data)
        #print(future.result())

    else:
        print(num, "is a not prime number")
        data = f"{num} is a not prime number - processed by {socket.gethostname()}"
        data = data.encode("utf-8")
        future = publisher.publish(publish_topic_path, data)
        #print(future.result())

    print(f"Received {message}.")

    message.ack()

streaming_pull_future = subscriber.subscribe(subscription_path, callback=callback)
print(f"Listening for messages on {subscription_path}..\n")

# Wrap subscriber in a 'with' block to automatically call close() when done.
with subscriber:
    try:
        # When `timeout` is not set, result() will block indefinitely,
        # unless an exception is encountered first.
        streaming_pull_future.result(timeout=timeout)
    except TimeoutError:
        streaming_pull_future.cancel()  # Trigger the shutdown.
        streaming_pull_future.result()  # Block until the shutdown is complete.