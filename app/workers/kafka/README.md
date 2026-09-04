# Kafka worker package

This package follows a service-oriented layout for the eventing layer.

## Structure

app/workers/kafka/
├── __init__.py
├── README.md
├── config.py                  # shared configuration
├── producer.py                # compatibility import entry point
├── core/                      # connection and exception types
│   ├── __init__.py
│   ├── client.py
│   └── exceptions.py
├── producers/                 # publishing components
│   ├── __init__.py
│   ├── base.py
│   ├── compat.py             # legacy KafkaProducer adapter
│   └── event_publisher.py
├── consumers/                # consumer runtime and analytics handlers
│   ├── __init__.py
│   ├── analytics_consumer.py
│   ├── base.py
│   ├── manager.py
│   └── handlers/
├── serializers/              # JSON / schema serialization
│   ├── __init__.py
│   ├── base.py
│   ├── json_serializer.py
│   └── event_schemas.py
├── events/                   # domain event envelopes
│   ├── __init__.py
│   └── envelopes.py
├── handlers/                 # event-family handlers
│   ├── __init__.py
│   └── appointment_events.py
├── middleware/               # retry + decorators
│   ├── __init__.py
│   └── decorators.py
└── compat/                   # backward-compatible public exports
    └── __init__.py

## Design intent

- Keep the canonical Kafka API under the worker package.
- Separate transport concerns from business logic.
- Preserve legacy imports via compatibility shims.
- Keep message contracts, handlers, and publishers explicit and easy to navigate.
