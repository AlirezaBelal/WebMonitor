import requests
from bs4 import BeautifulSoup
from plyer import notification
import time
import json

# Load configuration from the file
with open("config.json", "r") as config_file:
    config = json.load(config_file)

url = config["target_url"]
headers = config["headers"]
notification_title = config["notification"]["title"]
notification_message = config["notification"]["message"]
check_interval_seconds = config["check_interval_seconds"]
previous_data_file = config["previous_data_file"]


def check_for_updates():
    response = requests.get(url, headers=headers)
    soup = BeautifulSoup(response.content, 'html.parser')

    # Extract relevant information for comparison
    current_data = str(soup.find_all('div', class_='your-target-class'))

    # Load previous data from a file or create an empty string
    try:
        with open(previous_data_file, "r") as file:
            previous_data = file.read()
    except FileNotFoundError:
        previous_data = ""

    # Compare current and previous data
    if current_data != previous_data:
        # Update detected, notify the user
        notification.notify(
            title=notification_title,
            message=notification_message,
        )

        # Save the new data for future comparisons
        with open(previous_data_file, "w") as file:
            file.write(current_data)


# Run the script with the specified interval
while True:
    check_for_updates()
    time.sleep(check_interval_seconds)
