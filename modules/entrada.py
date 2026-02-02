from typing import List, Dict, Any, Union

def receber_requisicao(json_input: Union[List[Dict[str, Any]], Dict[str, Any]]) -> List[Dict[str, Any]]:
    # Aceita dict único e converte para lista
    if isinstance(json_input, dict):
        json_input = [json_input]
    elif not isinstance(json_input, list):
        raise ValueError("O input deve ser uma lista de objetos JSON (ou um objeto único).")

    if not json_input:
        raise ValueError("A lista de entrada está vazia.")

    required_keys = ("id", "lat", "lon")
    print(f"Validando {len(json_input)} subestações...")

    for index, item in enumerate(json_input):
        if not isinstance(item, dict):
            raise ValueError(f"Item {index}: cada item deve ser um objeto JSON (dict).")

        missing = [k for k in required_keys if k not in item]
        if missing:
            raise ValueError(f"Item {index}: Campos obrigatórios faltando: {', '.join(missing)}")

        # id
        if not isinstance(item["id"], str):
            raise ValueError(f"Item {index}: 'id' deve ser string")
        item_id = item["id"].strip()
        if not item_id:
            raise ValueError(f"Item {index}: 'id' não pode ser vazio")

        # lat (conversão separada da checagem de faixa)
        try:
            lat = float(item["lat"])
        except (TypeError, ValueError):
            raise ValueError(f"Item {index} ({item_id}): Latitude deve ser numérica")
        if not (-90.0 <= lat <= 90.0):
            raise ValueError(f"Item {index} ({item_id}): Latitude {lat} inválida")

        # lon
        try:
            lon = float(item["lon"])
        except (TypeError, ValueError):
            raise ValueError(f"Item {index} ({item_id}): Longitude deve ser numérica")
        if not (-180.0 <= lon <= 180.0):
            raise ValueError(f"Item {index} ({item_id}): Longitude {lon} inválida")

        # normaliza
        item["id"] = item_id
        item["lat"] = lat
        item["lon"] = lon

    print(f"Input validado com sucesso: {len(json_input)} ativos.")
    return json_input
