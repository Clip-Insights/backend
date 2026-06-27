from integrations.registry import get_analytics


def fetch_and_store_ga_data():
    get_analytics().fetch_and_store()
