import csv_exporter
import json_exporter
import stream_handler

class PipelineCoordinator:
    """A class to coordinate the data export process, delegating to appropriate exporters based on the specified format."""

    def export_data(self, data, format, output_path):
        """
        Export data to the specified format using the appropriate exporter.
        
        Args:
            data: The data to be exported.
            format (str): The export format, e.g., 'csv' or 'json'.
            output_path (str): The file path to save the exported data.
        
        Raises:
            ValueError: If the format is not supported.
        """
        try:
            if format == 'csv':
                csv_exporter.CSVExporter.export(data, output_path)
            elif format == 'json':
                json_exporter.JSONExporter.export(data, output_path)
            else:
                raise ValueError("Unsupported export format. Available formats: csv, json.")
        except Exception as e:
            print(f"An error occurred during export: {e}")
            # Additional error handling can be added here, e.g., logging
