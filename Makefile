.PHONY: up down test logs zip

up:
	docker compose up --build

down:
	docker compose down -v

test:
	docker compose -f docker-compose.test.yml up --build --abort-on-container-exit

logs:
	docker compose logs -f

zip:
	cd .. && zip -r sceneradar_project.zip sceneradar_project
