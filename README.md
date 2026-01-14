### Démo Stripe multi-compte (création Customer + Address Element)
Cette application est une **démo** (Flask + HTML/CSS/JS) qui simule une gestion **multi-comptes Stripe** :
- 1 produit avec 2 prix (EUR / USD) définis côté backend
- sélection d’un prix → formulaire de création client
- saisie d’adresse via **Stripe Address Element**
- création d’un **Stripe Customer toujours sur le compte master (EU par défaut)**, puis usage de la metadata **`Processing_Account`** pour indiquer le compte “de processing” associé au prix (contexte “Organization Resource Sharing”)

### Prérequis
- Python 3.10+
- Accès internet (pour charger `https://js.stripe.com/v3/`)
- 2 comptes Stripe (2 jeux de clefs) + 2 `price_id`

### Configuration
- **1) Copier le fichier d’exemple en `.env`**

```bash
cp stripe.env.example .env
```

- **2) Remplacer les placeholders dans `.env`**  
Tu dois définir, pour chaque alias (ex: `EU`, `US`) :
- `STRIPE_ACCOUNT_<ALIAS>_ACCOUNT_ID`
- `STRIPE_ACCOUNT_<ALIAS>_SECRET_KEY`
- `STRIPE_ACCOUNT_<ALIAS>_PUBLISHABLE_KEY`

Et définir le compte master (création des resources) :
- `STRIPE_MASTER_ACCOUNT_ALIAS` (par défaut `EU`)

- **3) Mettre tes vrais Price IDs dans `config/catalog.json`**
Remplace :
- `price_EUR_PLACEHOLDER`
- `price_USD_PLACEHOLDER`

### Autocomplete (Address Element)
Selon la doc Stripe, **si tu utilises l’Address Element seul**, tu dois fournir **ta propre clé Google Maps Places** via `autocomplete.apiKey` pour activer l’autocomplete. Si tu utilises Address Element + Payment Element, Stripe peut l’activer sans configuration additionnelle.  
Référence : [Stripe Address Element – Autocomplete](https://docs.stripe.com/elements/address-element#autocomplete)

Dans cette démo (Address Element seul), tu peux activer l’autocomplete en renseignant :
- `GOOGLE_MAPS_PLACES_API_KEY` dans `.env` (clé “browser”, à restreindre par HTTP referrer côté Google)

### Installation

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Lancement

```bash
python app.py
```

Puis ouvrir :
- `http://127.0.0.1:5000/`

### Endpoints utiles
- `GET /api/catalog`
- `GET /api/stripe/publishable-key?price_id=...`
- `POST /api/customers`
- `POST /api/subscriptions`
- `POST /api/processing-payment-intents`


