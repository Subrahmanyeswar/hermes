from typing import Generator, Iterable, TypeVar

T = TypeVar('T')

def filter_invalid_records(stream: Iterable[T]) -> Generator[T, None, None]:
    """
    Generator that filters out invalid records from a streaming list.
    A record is considered invalid if it is None or if it doesn't have a 'valid' field set to True.
    """
    for record in stream:
        if record is not None and hasattr(record, 'valid') and record.valid:
            yield record

# Example usage
def main():
    """
    Sample streaming data to demonstrate the filter_invalid_records generator.
    """
    data_stream = [{'valid': True, 'data': 'A'}, None, {'valid': False, 'data': 'B'}, {'valid': True, 'data': 'C'}]
    
    # Filter the data
    filtered_data = filter_invalid_records(data_stream)
    
    # Print the filtered data
    print("Filtered records:")
    for item in filtered_data:
        print(item)

if __name__ == "__main__":
    main()
