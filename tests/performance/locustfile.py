from locust import HttpUser, between, task


class SceneRadarUser(HttpUser):
    wait_time = between(1, 3)

    @task(4)
    def ranking(self):
        self.client.get("/api/ranking?genre=metal")

    @task(2)
    def cities(self):
        self.client.get("/api/cities")

    @task(2)
    def city_events(self):
        self.client.get("/api/cities/1/events?genre=metal")

    @task(1)
    def dashboard(self):
        self.client.get("/api/dashboard/1?genre=metal")
