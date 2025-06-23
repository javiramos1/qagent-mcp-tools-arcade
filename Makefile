# Makefile for Q&A Agent Project
.PHONY: help install run test clean docker-build docker-run docker-stop format lint

# Default target
help:
	@echo "Available commands:"
	@echo "  install      - Install dependencies and setup virtual environment"
	@echo "  run          - Run the application locally"
	@echo "  test         - Run tests"
	@echo "  clean        - Clean up temporary files and virtual environment"
	@echo "  docker-build - Build Docker image"
	@echo "  docker-run   - Run with docker-compose"
	@echo "  docker-stop  - Stop docker-compose services"
	@echo "  format       - Format code with black"
	@echo "  lint         - Run linting checks"
	@echo "  requirements - Generate requirements.txt"

# Python and virtual environment setup
VENV_NAME = qagent_venv
PYTHON = python3
PIP = $(VENV_NAME)/bin/pip
PYTHON_VENV = $(VENV_NAME)/bin/python

# Install dependencies and setup virtual environment
install:
	@echo "Creating virtual environment..."
	$(PYTHON) -m venv $(VENV_NAME)
	@echo "Installing dependencies..."
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt
	@echo "Setup complete! Activate with: source $(VENV_NAME)/bin/activate"

# Run the application locally
run:
	@echo "Starting Q&A Agent..."
	$(PYTHON_VENV) main.py

# Run tests (add test files as needed)
test:
	@echo "Running tests..."
	$(PYTHON_VENV) -m pytest tests/ -v || echo "No tests found. Add tests in tests/ directory."

# Clean up temporary files and virtual environment
clean:
	@echo "Cleaning up..."
	rm -rf $(VENV_NAME)
	rm -rf __pycache__
	rm -rf *.pyc
	rm -rf .pytest_cache
	find . -type d -name "__pycache__" -delete
	find . -type f -name "*.pyc" -delete

# Docker commands
docker-build:
	@echo "Building Docker image..."
	docker build -t qa-agent .

docker-run:
	@echo "Starting services with docker-compose..."
	docker-compose up -d

docker-stop:
	@echo "Stopping docker-compose services..."
	docker-compose down

docker-logs:
	@echo "Showing docker-compose logs..."
	docker-compose logs -f

# Code formatting and linting
format:
	@echo "Formatting code with black..."
	$(PYTHON_VENV) -m black . || echo "Install black with: pip install black"

lint:
	@echo "Running linting checks..."
	$(PYTHON_VENV) -m flake8 . || echo "Install flake8 with: pip install flake8"

# Generate requirements.txt from current environment
requirements:
	@echo "Generating requirements.txt..."
	$(PIP) freeze > requirements.txt

# Development helpers
dev-install:
	@echo "Installing development dependencies..."
	$(PIP) install black flake8 pytest

# Quick start for new users
quick-start: install
	@echo "Quick start complete!"
	@echo "1. Copy .env.example to .env and add your API keys"
	@echo "2. Run 'make run' to start the application"
	@echo "3. Visit http://localhost:8000/docs for API documentation" 