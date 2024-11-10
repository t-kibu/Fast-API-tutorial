from fastapi import BackgroundTasks, Depends, FastAPI
from fastapi.testclient import TestClient

from .dependencies import get_query_token, get_token_header
from .internal import admin
from .routers import items, users

app = FastAPI(dependencies=[Depends(get_query_token)])
client = TestClient(app)


# routerの呼び出し
app.include_router(users.router)
app.include_router(items.router)
app.include_router(
    admin.router,
    prefix="/admin",
    tags=["admin"],
    dependencies=[Depends(get_token_header)],
    responses={418: {"description": "I`m a reapot"}},
)


@app.get("/")
async def root():
    return {"message": "Hello Bigger Applications!"}


@app.get("/test/")
async def test_main():
    return {"msg": "Hello World"}


# ログ書き込み処理
def write_log(message: str):
    with open("log.txt", mode="a") as log:
        log.write(message)


# リクエストにクエリがあった場合、バックグラウンドでログを書き込むための処理。通知に対してDIする
def get_query(background_tasks: BackgroundTasks, q:  str | None = None):
    if q:
        message = f"found query: {q}\n"
        background_tasks.add_task(write_log, message)
    return q

# バックグラウンドで実行するタスク。メール送信後の通知を行うという体裁で通知するべきメッセージを決める
def write_notification(email: str, message=""):
    with open("log.txt", mode="w") as email_file:
        content = f"notification for {email}: {message}"
        email_file.write(content)


# 実際に通知を行う
@app.post("/send-notification/{email}")
async def send_notification(email: str, background_tasks: BackgroundTasks, q: str = Depends(get_query)):
    message = f"message to {email}\n"
    background_tasks.add_task(write_log, message)
    return {"message": "Notification sent in the background"}
