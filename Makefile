dev-up:
	docker-compose up -d

production-up:
	docker-compose -f docker-compose.yml -f production.yml up -d

down:
	docker-compose down

start:
	docker-compose start

stop:
	docker-compose stop

bash-twitter:
	docker exec -it twitter_01 bash

bash-iex:
	docker exec -it iex_01 bash

bash-manager:
	docker exec -it manager_01 bash

bash-db:
	docker exec -it postgresdb_01 bash

log-twitter:
	docker-compose logs twitter

log-iex:
	docker-compose logs iex

log-manager:
	docker-compose logs manager

log-db:
	docker-compose logs db

	log-db-data:
		docker-compose logs db-data

log-analytics:
	docker-compose logs analytics
