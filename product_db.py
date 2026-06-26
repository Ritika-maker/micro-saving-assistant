import pandas as pd
import json

def load_products(csv_path='products2.csv'):
    df = pd.read_csv(csv_path)
    return df.to_dict('records')

if __name__ == "__main__":
    products = load_products()
    print(json.dumps(products[:3], indent=2))