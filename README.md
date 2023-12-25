# WebMonitor

WebMonitor is a Python script designed for monitoring changes on a specified website. Stay informed about updates on your favorite web pages without the need for manual checks.

## Features

- **Configurability:** Easily adapt the script to your needs using the `config.json` file.
- **Notification System:** Receive desktop notifications for detected updates.
- **Interval Monitoring:** Regularly checks the target website at defined intervals.
- **Maintainability:** Keep configuration settings separate for easy customization.

## How to Use

1. Configure the target URL, headers, notification details, and other settings in the `config.json` file.
2. Run the script using Python (`python main.py`) to start monitoring the specified website.
3. Receive desktop notifications when updates are detected.

## Configuration

Adjust the `config.json` file to set up your preferred monitoring parameters.

```json
{
    "target_url": "https://example.com",
    "headers": {
        "User-Agent": "Your User Agent"
    },
    "notification": {
        "title": "Update Detected",
        "message": "There is a new update on the website."
    },
    "check_interval_seconds": 300,
    "previous_data_file": "previous_data.txt"
}
```

## Contribution

Contributions are welcome! Feel free to open issues and submit pull requests.
