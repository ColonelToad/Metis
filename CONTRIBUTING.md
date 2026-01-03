# Contributing to Metis

Thank you for your interest in contributing to Metis! This is currently a research/portfolio project, but contributions and feedback are welcome.

## Development Setup

See [SETUP.md](SETUP.md) for complete setup instructions.

## Code Style

### Python
- Follow PEP 8 style guidelines
- Use type hints where possible
- Format with `black` and lint with `flake8`
- Write docstrings for all public functions

```bash
pip install black flake8
black research/
flake8 research/
```

### Rust
- Follow standard Rust conventions
- Use `cargo fmt` for formatting
- Use `cargo clippy` for linting
- Write tests for all public APIs

```bash
cargo fmt
cargo clippy --all-targets --all-features
cargo test
```

### Commit Messages
- Use clear, descriptive commit messages
- Start with a verb (Add, Fix, Update, Remove, etc.)
- Reference issues when applicable

Examples:
```
Add TWAP execution algorithm with slicing logic
Fix order book spread calculation for edge cases
Update RAG pipeline to use Milvus 2.3.3
```

## Project Structure Guidelines

### Adding New Features

**Python Research Components** (`research/`):
- Data ingestion: Add clients to `data_ingest/`
- Features: Add engineering modules to `features/`
- Models: Add ML models to `models/`
- Backtests: Add testing frameworks to `backtest/`

**Rust Execution Components** (`execution/`):
- Order book logic: Modify `orderbook/`
- Execution algos: Add algorithms to `execution_algos/`
- FIX protocol: Extend `fix_client/`
- Signal interface: Update `signal_interface/`

**RAG Pipeline** (`rag/`):
- Document sources: Add ingesters to `indexing/`
- Retrieval: Modify `retrieval_pipeline.py`
- LLM generation: Add generators to `generation/`

## Testing

### Python Tests
```bash
cd research
pytest tests/ -v
```

### Rust Tests
```bash
cd execution
cargo test --all
cargo test --package orderbook -- --nocapture  # Detailed output
```

### Integration Tests
```bash
# Start infrastructure
cd infrastructure
docker-compose up -d

# Run end-to-end tests
python tests/integration/test_e2e_pipeline.py
```

## Performance Benchmarks

### Rust Benchmarks
```bash
cd execution/orderbook
cargo bench
```

Expected targets:
- Order book update: <10μs per event
- TWAP slice generation: <1ms for 100 slices
- Signal serialization: <100μs

### Python Profiling
```bash
cd research
python -m cProfile -o profile.stats models/train_baseline_lstm.py
python -c "import pstats; p = pstats.Stats('profile.stats'); p.sort_stats('cumulative').print_stats(20)"
```

## Documentation

- Update README.md for user-facing changes
- Update ROADMAP.md for feature milestones
- Add docstrings/comments for complex logic
- Create examples in `examples/` for new features

## Pull Request Process

1. **Fork and Branch**: Create a feature branch from `main`
2. **Develop**: Make changes following code style guidelines
3. **Test**: Ensure all tests pass locally
4. **Document**: Update relevant documentation
5. **Commit**: Write clear commit messages
6. **Push**: Push to your fork
7. **PR**: Create pull request with description of changes

### PR Checklist
- [ ] Code follows project style guidelines
- [ ] Tests added for new features
- [ ] All tests pass locally
- [ ] Documentation updated
- [ ] No breaking changes (or clearly documented)
- [ ] Performance benchmarks maintained or improved

## Reporting Issues

Use GitHub Issues with the following labels:
- `bug`: Something isn't working
- `enhancement`: New feature request
- `performance`: Performance optimization
- `documentation`: Documentation improvements
- `question`: Questions about usage

Include:
- Clear description of issue/feature
- Steps to reproduce (for bugs)
- Expected vs actual behavior
- Environment details (OS, Python/Rust version)
- Relevant logs or error messages

## Research Ideas Welcome

If you have ideas for:
- New climate/policy features
- Advanced execution algorithms
- ML model improvements
- Alternative data sources
- Performance optimizations

Please open a discussion issue to get feedback before implementing.

## Code of Conduct

- Be respectful and constructive
- Focus on technical merits
- Help newcomers learn
- Keep discussions on-topic

## License

By contributing, you agree that your contributions will be licensed under the MIT License.

## Questions?

- Open a GitHub Issue
- Check existing documentation in `docs/`
- Review closed issues for similar questions
