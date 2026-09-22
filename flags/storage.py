import json
import os

class FlagStorage:
    """A class to handle storage and retrieval of feature flags using a JSON file."""

    def __init__(self, file_path='flags.json'):
        """Initialize the FlagStorage with a file path for JSON storage."""
        self.file_path = file_path

    def save_flag(self, flag_data):
        """Save feature flag data to the JSON file."""
        with open(self.file_path, 'w') as f:
            json.dump(flag_data, f)

    def load_flag(self):
        """Load feature flag data from the JSON file, returning an empty dict if the file doesn't exist."""
        if not os.path.exists(self.file_path):
            return {}
        with open(self.file_path, 'r') as f:
            return json.load(f)

    def update_flag(self, flag_id, new_data):
        """Update an existing feature flag with new data."""
        data = self.load_flag()
        if flag_id in data:
            data[flag_id].update(new_data)
        else:
            data[flag_id] = new_data
        self.save_flag(data)

    def delete_flag(self, flag_id):
        """Delete a feature flag from storage."""
        data = self.load_flag()
        if flag_id in data:
            del data[flag_id]
            self.save_flag(data)

    def get_all_flags(self):
        """Retrieve all feature flags."""
        return self.load_flag()