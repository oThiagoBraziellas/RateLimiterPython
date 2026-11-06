# RateLimiter em Python

Duas implementações de limitação de taxa em Python puro: **token bucket** e **sliding window log**, ambas com relógio injetável, custo ponderado por requisição, segurança entre threads e uma camada por chave (usuário, IP, chave de API). Todo o comportamento temporal é testado sem `sleep`, usando um relógio falso.

## Por que este projeto

Rate limiting aparece em praticamente toda entrevista de backend e system design ("projete um limitador de requisições para uma API") e em todo produto real: gateways de API, proteção contra abuso, filas e cotas de uso. A pergunta de fundo é escolher o algoritmo certo e saber justificar: o token bucket permite rajadas controladas com memória constante; o sliding window log é exato, sem o problema de rajada dupla na virada de janelas fixas, mas custa memória proporcional ao limite. Este projeto implementa os dois lado a lado para tornar essa comparação concreta.

## Recursos

- `TokenBucket(capacity, refill_rate)`: rajada de até `capacity`, taxa média de `refill_rate` tokens por segundo, recarga calculada de forma preguiçosa.
- `SlidingWindowLog(limit, window)`: no máximo `limit` requisições em qualquer intervalo de `window` segundos.
- `Decision` com `allowed`, `remaining` e `retry_after` (segundos até a mesma requisição passar), pronto para virar o cabeçalho `Retry-After`.
- Custo por requisição (`allow(cost=3)`), útil para endpoints mais caros.
- `KeyedLimiter`: um limitador independente por chave, com `prune` para liberar chaves ociosas.
- `FakeClock` para testes determinísticos; qualquer função sem argumentos que devolva segundos serve como relógio.
- Demonstração em linha de comando que compara os dois algoritmos sob a mesma carga.

## Como executar

Requer Python 3.8 ou superior.

```python
from rate_limiter import TokenBucket, SlidingWindowLog, KeyedLimiter

bucket = TokenBucket(capacity=10, refill_rate=5)       # 5 req/s, rajada de 10
decision = bucket.allow()
if not decision:
    print(f"tente de novo em {decision.retry_after:.2f}s")

por_usuario = KeyedLimiter(lambda: SlidingWindowLog(limit=100, window=60))
por_usuario.allow("usuario-42")
```

Demonstração (3 requisições por segundo simulado contra os dois algoritmos):

```bash
python3 -m rate_limiter
```

## Como testar

```bash
python3 -m unittest -v
```

Os testes cobrem rajada e recarga, limite de capacidade, recarga fracionária, `retry_after` exato (avançando o relógio pelo valor devolvido e verificando que a requisição passa), a ausência de rajada na virada de janela, custo ponderado, custo maior que o limite, validação de argumentos e uma corrida com oito threads que garante que o total concedido nunca ultrapassa a capacidade.

## Decisões de projeto

- **Recarga preguiçosa.** O token bucket não usa thread de fundo: a cada chamada calcula `tokens = min(capacity, tokens + elapsed * rate)`. Tempo e memória são O(1) por chave.
- **Sliding window log exato.** Uma `deque` guarda um timestamp por requisição aceita; a avaliação remove do início o que saiu da janela. Memória O(limite) por chave, tempo amortizado O(1). Alternativas mais baratas (janela fixa, sliding window counter) aproximam o resultado com memória constante.
- **Rajada vs. suavidade.** O token bucket deixa passar `capacity` requisições de uma vez e depois impõe a taxa; o sliding window nunca passa de `limit` em nenhuma janela, mas também não "perdoa" tempo ocioso.
- **`retry_after` calculado, não adivinhado.** No bucket vem de `(custo - tokens) / taxa`; no log, do instante em que as entradas mais antigas saem da janela. Custo acima da capacidade devolve `inf`, pois nunca passaria.
- **Relógio monotônico injetável.** O padrão é `time.monotonic`, imune a ajustes do relógio de parede; nos testes o tempo é avançado manualmente.
- **Um `Lock` por limitador.** A verificação e a atualização são atômicas; chaves diferentes não competem entre si.
- **Trade-off:** o estado está na memória de um processo. Em uma frota de servidores seria necessário um armazenamento compartilhado (por exemplo Redis com script atômico) ou aceitar um limite aproximado por nó.

## Estrutura de pastas

```
RateLimiter/
├── rate_limiter/
│   ├── __init__.py
│   ├── __main__.py     # demonstração comparativa
│   ├── clock.py        # FakeClock
│   └── limiters.py     # TokenBucket, SlidingWindowLog, KeyedLimiter, Decision
├── tests/
│   └── test_limiters.py
├── LICENSE
└── README.md
```

## Limitações conhecidas

- Estado apenas em memória e por processo; não há limitação distribuída.
- `KeyedLimiter` não expira chaves sozinho: é preciso chamar `prune`.
- O sliding window log não é indicado para limites muito altos (milhões por janela) por causa da memória.
- Não há integração pronta com frameworks web nem geração automática de cabeçalhos HTTP.

## Licença

MIT. Veja o arquivo [LICENSE](LICENSE).
