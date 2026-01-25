# Polymarket Arbitrage Bot

Monitors Polymarket binary prediction markets for pricing inefficiencies and executes risk-free arbitrage.

## How It Works

In a binary market, YES + NO shares should always equal $1.00. During volatile live events (esports, elections), prices can briefly desync:

```
YES: $0.48
NO:  $0.49
Total: $0.97  ← should be $1.00
```

Bot buys both sides for $0.97, guarantees $1.00 payout. **$0.03 profit, zero risk.**

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     Hetzner VPS (K3s)                       │
│                                                             │
│  ┌───────────────────────────────────────────────────────┐ │
│  │              polymarket-arb-bot                        │ │
│  │                                                        │ │
│  │   ┌─────────────┐    ┌─────────────┐                  │ │
│  │   │  Gamma API  │───▶│  Arb Logic  │                  │ │
│  │   │  (markets)  │    │             │                  │ │
│  │   └─────────────┘    └──────┬──────┘                  │ │
│  │                             │                          │ │
│  │   ┌─────────────┐    ┌──────▼──────┐                  │ │
│  │   │  CLOB API   │◀───│   Execute   │                  │ │
│  │   │  (orders)   │    │   Trades    │                  │ │
│  │   └─────────────┘    └─────────────┘                  │ │
│  └───────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DRY_RUN` | `true` | Read-only mode, no trades |
| `MIN_SPREAD` | `0.02` | Min profit to act ($0.02 = 2%) |
| `MAX_POSITION_SIZE` | `50` | Max USDC per trade |
| `POLL_INTERVAL` | `2.0` | Seconds between scans |
| `POLYMARKET_PRIVATE_KEY` | — | Wallet private key (live only) |
| `POLYMARKET_FUNDER_ADDRESS` | — | Wallet address (live only) |

## Deployment

### 1. Add to ArgoCD

In your `m-town-infra` repo, add to `base/argocd/apps.yaml`:

```yaml
---
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: polymarket-arb-bot
  namespace: argocd
spec:
  project: default
  source:
    repoURL: https://github.com/mx-town/polymarket-arb-bot.git
    targetRevision: main
    path: k8s
  destination:
    server: https://kubernetes.default.svc
    namespace: default
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
```

### 2. Create Credentials Secret (for live trading)

```bash
kubectl create secret generic polymarket-credentials \
  --from-literal=private_key=YOUR_PRIVATE_KEY \
  --from-literal=funder_address=YOUR_WALLET_ADDRESS
```

### 3. Enable Live Trading

Edit `k8s/configmap.yaml`:

```yaml
data:
  dry_run: "false"  # Enable real trades
```

## Getting Polymarket Credentials

1. Go to [reveal.polymarket.com](https://reveal.polymarket.com)
2. Connect your wallet
3. Export your private key
4. Your funder address is your Polymarket deposit address

## Quick Commands

```bash
# View logs
kubectl logs -f deployment/polymarket-arb-bot

# Check status
kubectl get pods -l app=polymarket-arb-bot

# Restart after config change
kubectl rollout restart deployment/polymarket-arb-bot

# Scale down (pause)
kubectl scale deployment/polymarket-arb-bot --replicas=0
```

## Market Tags

Bot scans these market categories by default:
- `esports` — League of Legends, Dota 2, CS:GO
- `gaming` — General gaming events
- `politics` — Elections, policy
- General binary markets

## Risks & Caveats

1. **Execution risk** — Prices can move before both orders fill
2. **Fees** — Polymarket charges fees on trades
3. **Liquidity** — Low liquidity markets may not have enough volume
4. **Rate limits** — API has rate limits
5. **Geographic restrictions** — Polymarket not available in all regions

## Costs

| Component | Cost |
|-----------|------|
| Bot hosting | $0 (runs on existing K3s) |
| Trading capital | Your USDC |
| Polymarket fees | ~0.5-1% per trade |

## License

MIT
