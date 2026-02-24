# ProductSync — Backend API

Scraper de produtos por marca com export CSV e futura integração Amazon ASIN.

## 🚀 Deploy no Railway (passo a passo)

### 1. Suba este código no GitHub
- Crie um repositório novo no GitHub chamado `productsync-backend`
- Faça upload de todos os arquivos desta pasta

### 2. Deploy no Railway
- Acesse railway.app → New Project → GitHub Repository
- Selecione o repositório `productsync-backend`
- O Railway detecta Python automaticamente e faz o deploy

### 3. Pegue a URL pública
- Após o deploy, vá em Settings → Networking → Generate Domain
- Você terá uma URL tipo: `https://productsync-backend.up.railway.app`

## 📡 Endpoints da API

### Buscar produtos
```
GET /scrape/walmart?brand=elf&max_items=40
```

### Exportar CSV direto
```
GET /export/csv?brand=elf&max_items=40
```

### Parâmetros disponíveis
| Parâmetro | Valores | Default |
|-----------|---------|---------|
| brand | qualquer texto | obrigatório |
| max_items | 1–200 | 40 |
| sort | best_match, price_low, price_high, rating | best_match |

## 🔧 Rodar localmente

```bash
pip install -r requirements.txt
uvicorn main:app --reload
```

Acesse: http://localhost:8000/docs

## 📦 Estrutura dos dados retornados

```json
{
  "brand": "elf",
  "source": "walmart",
  "count": 40,
  "products": [
    {
      "name": "e.l.f. Poreless Putty Primer",
      "brand": "e.l.f.",
      "sku": "123456789",
      "item_id": "987654321",
      "upc": "609332825057",
      "price": "$12.00",
      "category": "Beauty",
      "url": "https://walmart.com/...",
      "rating": 4.7,
      "source": "Walmart",
      "asin": ""
    }
  ]
}
```
