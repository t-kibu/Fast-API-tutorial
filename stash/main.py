import json
import time as module_time
from contextlib import asynccontextmanager
from datetime import datetime, time, timedelta, timezone
from enum import Enum
from sqlite3 import InternalError
from typing import Annotated, Any, List, Literal, Optional, Set, Union
from uuid import UUID

import jwt
from fastapi import (
    Body,
    Cookie,
    Depends,
    FastAPI,
    File,
    Form,
    Header,
    HTTPException,
    Path,
    Query,
    Request,
    UploadFile,
    status,
)
from fastapi.encoders import jsonable_encoder
from fastapi.exception_handlers import (
    http_exception_handler,
    request_validation_exception_handler,
)
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jwt.exceptions import InvalidTokenError
from passlib.context import CryptContext
from pydantic import BaseModel, EmailStr, Field, HttpUrl
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlmodel import Field, Session, SQLModel, create_engine, select
from starlette.exceptions import HTTPException as StarletteHTTPException

app = FastAPI()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")


# to get a string like this run:
# openssl rand -hex 32
SECRET_KEY = "09d25e094faa6ca2556c818166b7a9563b93f7099f6f0f4caa6cf63b88e8d3e7"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30


# DBSettings
sqlite_file_name = "database.db"
sqlite_url = f"sqlite:///{sqlite_file_name}"

# 同じSQLiteデータベースを異なるスレッドで使用する
connect_args = {"check_same_thread": False}
engine = create_engine(sqlite_url, connect_args=connect_args)


origins = [
    "http://localhost.tiangolo.com",
    "https://localhost.tiangolo.com",
    "http://localhost",
    "http://localhost:8080",
]

# middlewareにCORSに関する設定を追加
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


fake_users_db = {
    "johndoe": {
        "username": "johndoe",
        "full_name": "John Doe",
        "email": "johndoe@example.com",
        "hashed_password": "$2b$12$EixZaYVK1fsbw1ZfbX3OXePaWxn96p36WQoeG6Lruj3vjPGga31lW",
        "disabled": False,
    }
}


# middleware
@app.middleware("http")
async def add_process_time_header(request: Request, call_next):
    """httpリクエスト全てに対して実行される"""
    # 開始時間を計測
    start_time = module_time.perf_counter()
    # 次の処理（エンドポイント）を実行し、レスポンスを取得
    response = await call_next(request)
    # 処理終了後に経過時間を計算
    process_time = module_time.perf_counter() - start_time
    # レスポンスヘッダーに処理時間を追加
    response.headers["X-Process-Time"] = str(process_time)
    return response


# CORSのMiddleware


# nameからvalueを取り出すときはClass[name].value、valueからnameを取り出すときはClass(value).name
class ModelName(str, Enum):
    ALEXNET = "alexnet"
    RESNET = "resnet"
    LENET = "lenet"


# デコレータでHTTPメソッド(オペレーション)をPathといっしょに定義
@app.get("/models/{model_name}")
# 実行関数。非同期にしたいのならasyncをつける
async def get_model(model_name: ModelName):
    return {"model": ModelName(model_name).name, "value": model_name}


# 上から順に処理される
# @app.get("/users/{user_id}")
# async def read_user(user_id: str):
#     return {"user_id": user_id}


# ファイルパスを指定することもできる
@app.get("/files/{file_path:path}")
async def read_file(file_path: str):
    return {"file_path": file_path}


# # パスパラメータとクエリパラメータは順不同でもよい
# @app.get("/users/{user_id}/items/{item_id}")
# async def read_user_item(
#     user_id: int, item_id: str, q: Optional[str] = None, short: bool = False
# ):
#     item = {"item_id": item_id, "owner_id": user_id}
#     if q:
#         item.update({"q": q})
#     if not short:
#         item.update(
#             {"description": "This is an amazing item that has a long description"}
#         )
#     return item


"""
クエリパラメータを必須にするのならデフォルト値は設定しない。
この場合は

- http://127.0.0.1:8000/users/foo-user

こちらのURLはエラーとなる。

‐ http://127.0.0.1:8000/users/foo-user?needy=sooooneedy

とneedyに相当する値をセットして叩かないといけない
"""


@app.get("/users/{user_id}")
async def read_user(user_id: int, needy: str):
    user = {"user_id": user_id, "needy": needy}
    return user


# クエリパラメータはデフォルト値有り無しを同時に設定できる。ただし、位置引数に注意
@app.get("items/{item_id}")
async def read_user_item(
    item_id: str, needy: str, skip: int, limit: Optional[int] = None
):
    item = {"item_id": item_id, "needy": needy, "skip": skip, "limit": limit}
    return item


class Image(BaseModel):
    # 文字列は有効なURLであることが確認され、そのようにJSONスキーマ・OpenAPIで文書化される
    url: HttpUrl
    name: str


class Item(BaseModel):
    """
    # 関数パラメータは以下の様に認識されます:
    # パラメータがパスで宣言されている場合は、優先的にパスパラメータとして扱われます。
    # パラメータが単数型 (int、float、str、bool など)の場合はクエリパラメータとして解釈されます。
    # パラメータが Pydantic モデル型で宣言された場合、リクエストボディとして解釈されます。
    """

    # Optional以外はすべて必須となり、これがそのままリクエストボディのモデルとなる
    name: str = Field()
    description: Optional[str] = Field(
        default=None, title="The description of the item", max_length=300
    )
    price: float = Field(gt=0, description="The price must be greater than zero")
    tax: Optional[float] = None
    tags: Set[str] = set()
    image: Union[List[Image], None] = None
    # Open API等のドキュメントにおいてモデルサンプルを設定できる
    # 各Fieldにexamplesを渡すでもよい
    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "name": "Foo",
                    "description": "A very nice Item",
                    "price": 35.4,
                    "tax": 4.5,
                }
            ]
        }
    }


class Offer(BaseModel):
    name: str
    description: Optional[str] = None
    price: float
    items: List[Item]


class User(BaseModel):
    username: str
    full_name: Optional[str] = None


class FilterParams(BaseModel):
    # 以下で定義するパラメータ以外はクエリパラメータとして受け付けないようにする
    model_config = {"extra": "forbid"}

    limit: int = Field(100, gt=0, le=100)
    offset: int = Field(0, ge=0)
    order_by: Literal["created_at", "updated_at"] = "created_at"
    tags: Set[str] = set()


# Cookieの自作
class Cookies(BaseModel):
    # クラスで定義したフィールド以外のCookieの受け取りを拒否する場合はmodel_configに{"extra": "forbid"}を設定
    model_config = {"extra": "forbid"}

    session_id: str
    facebook_tracker: str | None = None
    google_tracker: str | None = None


# Headerの自作
class CommonHeaders(BaseModel):
    # 同様に定義したフィールド以外を禁止できる
    model_config = {"extra": "forbid"}

    host: str
    save_data: bool
    if_modified_since: str | None = None
    transparent: str | None = None
    x_tag: list[str] = []


class UserBase(BaseModel):
    username: str
    email: EmailStr
    full_name: Optional[str] = None


class UserIn(BaseModel):
    password: str


class UserOut(BaseModel):
    pass


class UserInDB(BaseModel):
    hashed_password: str


class FormData(BaseModel):
    username: str
    password: str


"""
Pathを指定すると、クエリパラメータも設定できる。ｑとshortがクエリパラメータとなる
このAPIはリクエスト的に以下のようなURLとなる。
‐ http://127.0.0.1:8000/items/foo?short=1
‐ http://127.0.0.1:8000/items/foo?short=True
‐ http://127.0.0.1:8000/items/foo?short=true
‐ http://127.0.0.1:8000/items/foo?short=on
‐ http://127.0.0.1:8000/items/foo?short=yes
"""


# ファイルアップロード系(FileはFormを継承している)
@app.post("/files/")
async def create_file(file: Annotated[bytes, File()]):
    return {"file_size": len(file)}


# FastAPIの場合はbytesにFileをデフォルト値として指定するのではなく、UploadFileを利用すると良い(bytesと同様にファイル名やcontent_nameなどにアクセスもできる)
@app.post("/upload_file/")
async def create_upload_file(file: UploadFile):
    # async(非同期)の場合はawaitをつける
    contents = await file.read()
    return {"filename": file.filename, "contents": contents}


def create_upload_file_not_async(file: UploadFile):
    # asyncではない場合、そのまま取れる
    contents = file.file.read()
    return {"contents": contents}


# UploadFileも当然Optionalにできる。またFile()と併用してAnnotatedを使用してメタデータをつけることもできる
@app.post("/upload_file2/")
async def create_upload_file_optional(
    file: (
        Annotated[UploadFile, File(description="A file read as UploadFile")] | None
    ) = None
):
    return {"file": file}


# 複数のファイルを受け付けたい場合はListで型付けできる
@app.post("/upload_files/")
async def create_upload_files(
    files: Annotated[List[UploadFile], File(description="UploadFiles")] | None = None
):
    return {"file": files}


# ファイル以外にリクエストで受け取るべき値(Formからのデータとか)がある場合は、File()・UploadFile()とForm()を併用する
@app.post("/multi_files/")
async def create_files(
    file: bytes = File(), upload_file: UploadFile = File(), token: str = Form()
):
    return {
        "file_size": len(file),
        "token": token,
        "uploadFile_content_type": upload_file.content_type,
    }


# デフォルト値をレスポンスに含めたくない場合はresponse_model_exclude_unset=Trueとする
@app.get("/items/{item_id}", response_model=Item, response_model_exclude_unset=True)
async def read_item(item_id: int, q: Optional[str] = None, short: bool = False):
    item = {"item_id": item_id}
    if q:
        item.update({"q": q})
    if not short:
        item.update(
            {"description": "This is an amazing item that has a long description"}
        )
    return item


def fake_password_hasher(raw_password: str):
    return "supersecret" + raw_password


def fake_save_user(user_in: UserIn):
    hashed_password = fake_password_hasher(user_in.password)
    user_in_db = UserInDB(**user_in.model_dump, hashed_password=hashed_password)
    print("User saved! ......not really")
    return user_in_db


# Form系の入力の場合はFormを使う(FormはBodyの継承である)
@app.post("/login/")
async def login(data: Annotated[FormData, Form()]):
    return data


# レスポンスの型付けを指定する場合は引数にresponse_modelを指定する
# リクエストボディとしてはUserInを使うが、レスポンスとしてはUserOutを使う(何を受け取り、何を返すかということの基本的な定義)
@app.post("/user/", response_model=UserOut)
async def create_user(user: UserIn) -> Any:
    return user


@app.get("/cookies/")
async def read_cookies(cookies: Annotated[Cookies, Cookie()]):
    return cookies


@app.get("/common_headers")
async def read_common_headers(headers: Annotated[CommonHeaders, Header()]):
    return headers


@app.post("/items/")
async def create_item(item: Item, status_code=status.HTTP_201_CREATED):
    # Pythonだとdict()だが、Pydanticとしては非推奨なのでmodel_dumpを使う
    item_dict = item.model_dump()
    if item.tax:
        price_with_tax = item.price + item.tax
        item_dict.update({"price_with_tax": price_with_tax})
    return item_dict


# # item_idはPath、itemはリクエストボディ、qはクエリパラメータ
# @app.put("/items/{item_id}")
# async def update_item(item_id: int, item: Item, q: Optional[str] = None):
#     result = {"item_id": item_id, **item.model_dump()}
#     if q:
#         result.update({"q": q})
#     return result


# # デフォルト値以外に最小・最大文字数を設定し、正規表現で合致するもの以外をクエリパラメータとして弾く
# @app.get("/items/")
# async def read_items(
#     q: Optional[str] = Query(
#         default=None, min_length=3, max_length=50, pattern="^fixedquery$"
#     )
# ):
#     results = {"items": [{"item_id": "Foo"}, {"item_id": "Bar"}]}
#     if q:
#         results.update({"q": q})
#     return results


# # クエリパラメータがListの場合。list型のクエリパラメータを宣言するには明示的にQueryを使用する
# # QueryにtitleやdescriptionをつけるとそのままOpen APIのDocsに記載される
# # NOTE: クエリパラメータ名にエイリアスを用いる場合はaliasを指定し、それが非推奨(キャメルやケバブケースでの指定だった)場合はdeprecated=Trueを指定するとDocsに記載される
# @app.get("/items/")
# async def read_items(
#     q: Optional[str] = Query(
#         default=None,
#         title="Query string",
#         description="Query string for the items to search in the database that have a good match",
#         min_length=3,
#     ),
# ):
#     results = {"items": [{"item_id": "Foo"}, {"item_id": "Bar"}]}
#     if q:
#         results.update({"q": q})
#     return results


# # item_idには0<n<=1以上のintが入る(gtならより大きい、ltならより小さい、leなら以下)
# # Path及びクエリパラメータの前に*を指定すると位置引数の順序制約を無視できる
# @app.get("/items/{item_id}")
# async def read_items(*, q: str, item_id: int = Path(title="The ID of the item to get", ge=1, lt=0), size:float = Query(gt=0, lt=10.5)):
#     results = {"item_id": item_id}
#     if q:
#         results.update({"q": q})
#     return results


@app.get("/items/")
async def read_items(filter_query: Annotated[FilterParams, Query()]):
    return filter_query


# 既にリクエストボディが決まっている場合で追加でリクエストボディに含めたい場合はBody()を使う
# またリクエストボディをKey‐Valueにしたい場合はBodyにembedを指定する
@app.put("/items/{item_id}")
async def update_item(
    item_id: int,
    user: User,
    item: Item = Body(
        examples=[
            {
                "name": "Foo",
                "description": "A very nice Item",
                "price": 35.4,
                "tax": 3.2,
            }
        ],
    ),
    # item: Item = Body(embed=True),
    importance: int = Body(gt=0),
    q: Optional[str] = None,
):
    results = {"item_id": item_id, "item": item, "user": user, "importance": importance}
    if q:
        results = {"q": q}
    return results


@app.put("/items/{item_id}")
async def update_item2(item_id: int, item: Item = Body(embed=True)):
    results = {"item_id": item_id, "item": item}
    return results


@app.post("/offers/")
async def create_offer(offer: Offer):
    return offer


@app.post("/images/multiple/")
async def create_multiple_images(images: List[Image]):
    return images


# 各種データ型も完備
@app.put("/typing/{type_id}")
async def read_types(
    type_id: UUID,
    start_datetime: datetime = Body(),
    end_datetime: datetime = Body(),
    process_after: timedelta = Body(),
    repeat_at: Optional[time] = Body(default=None),
):

    start_process = start_datetime + process_after
    duration = end_datetime - start_process

    return {
        "type_id": type_id,
        "start_datetime": start_datetime,
        "end_datetime": end_datetime,
        "process_after": process_after,
        "repeat_at": repeat_at,
        "start_process": start_process,
        "duration": duration,
    }


# Cookieも型として指定できる
@app.get("/items/")
async def read_cookie(ads_id: Optional[str] = Cookie(default=None)):
    return {"ads_id": ads_id}


# Headerも同様
@app.get("/headers/")
async def read_headers(user_agent: Optional[str] = Header(default=None)):
    return {"User-Agent": user_agent}


# Pythonではケバブケースは認められないので、Headerの場合はアンダースコアを自動的にケバブにする処理が働く
# 変換したくないときはHeaderのconvert_underscoresにFalseを設定
@app.get("/headers2/")
async def read_headers2(
    strange_header: Optional[str] = Header(default=None, convert_underscores=False)
):
    return {"strange_header": strange_header}


# ヘッダーの値が重複、つまり同じヘッダーで複数の値を保つ場合はListにする
@app.get("/headers3/")
async def read_headers3(x_token: Optional[List[str]] = Header(default=None)):
    return {"X-Token values": x_token}


items = {"foo": "The Foo Wrestlers"}


class UnicornException(Exception):
    def __init__(self, name: str):
        self.name = name


# カスタム例外も作ることができる
@app.exception_handler(UnicornException)
async def unicorn_exception_handler(request: Request, exc: UnicornException):
    return JSONResponse(
        status_code=418,
        content={"message": f"Oops! {exc.name} did something. There goes a rainbow..."},
    )


# StarletteHTTPExceptionを継承しているのがFastAPIのHTTPExceptionだが、独自の例外を追加したい場合は継承元で登録しておく必要がある
@app.exception_handler(StarletteHTTPException)
async def validation_exception_handler(request, exc):
    return PlainTextResponse(str(exc.detail), status_code=exc.status_code)


# 組み込みの例外のオーバーライドもできる
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request, exc):
    return PlainTextResponse(str(exc), status_code=400)


# 無効となったRequestBodyを返しつつ例外を出す
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content=jsonable_encoder({"detail": exc.errors(), "body": exc.body}),
    )


# もちろんFastAPI組み込みの例外もある
@app.exception_handler(StarletteHTTPException)
async def custom_http_exception_handler(request, exc):
    print(f"OMG! An HTTP error!: {repr(exc)}")
    return await http_exception_handler(request, exc)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request, exc):
    print(f"OMG! The client sent invalid data!: {exc}")
    return await request_validation_exception_handler(request, exc)


@app.get("/unicorns/{name}")
async def read_unicorn(name: str):
    if name == "yolo":
        raise UnicornException(name=name)
    return {"unicorn_name": name}


@app.get("/items_with_e/{item_id}")
async def read_item_with_exception(item_id: str):
    if item_id not in items:
        raise HTTPException(
            status_code=404,
            detail="Item not found",
            headers={"X-Error": "There goes my error"},
        )
    return {"item": items[item_id]}


@app.get("/custom_exception/{id}")
async def test_exception(id: int):
    if id == 3:
        raise HTTPException(status_code=418, detail="Nope! I don`t like 3.")
    return {"id": id}


# OpenAPIに上がること意識してより、docsを充実させる書き方もできる
# tagsでAPIごとに区分け、summaryで要旨、descriptionで詳細、docstringもつけるとそれも反映
class Card(BaseModel):
    name: str
    description: Optional[str] = None
    price: float
    tax: Optional[float] = None
    tags: Set[str] = set()


class Player(BaseModel):
    name: str
    age: int
    last_buy: datetime


cards = {
    "card1": {"name": "test", "price": 50.2},
    "card2": {
        "name": "test2",
        "description": "The bartenders",
        "price": 62,
        "tax": 20.2,
    },
    "card3": {
        "name": "test3",
        "description": None,
        "price": 50.2,
        "tax": 10.5,
        "tags": [],
    },
}


@app.post(
    "/cards/",
    response_model=Card,
    tags=["cards"],
    summary="Create an card",
    description="Create an card with all the information, name, description, price, tax and a set of unique tags",
    response_description="The created Item",
)
async def create_card(card: Card):
    """
    Create an card with all the information:

    - **name**: each card must have a name
    - **description**: a long description
    - **price**: required
    - **tax**: if the card doesn't have tax, you can omit this
    - **tags**: a set of unique tag strings for this card
    """
    return card


@app.get(
    "/cards/",
    response_model=Card,
    tags=["cards"],
    summary="Read an card",
    description="Read an card with all the information, name, description, price, tax and a set of unique tags",
)
async def read_cards():
    return [{"name": "Foo", "price": 42}]


@app.put("/cards/{card_id}", response_model=Card)
async def update_card(card_id: str, card: Card):
    update_card_encoded = jsonable_encoder(card)
    cards[card_id] = update_card_encoded
    return update_card_encoded


# あまり使わないけどPATCHの場合はPUTと違い受け取るべきデータだけ受け取ることを意識する
@app.patch("/cards/{card_id}", response_model=Card)
async def update_card_patch(card_id: str, card: Card):
    """PUT及びPATCHについて
    敢えてPATCHを使う場合は更新するべきデータだけを抽出することを意識する。
    過程は以下。
    1.  保存されているデータを取得します。
    2.  そのデータをPydanticモデルにいれます。
    3.  入力モデルからデフォルト値を含まないdictを生成します（exclude_unsetを使用します）。
        この方法では、モデル内のデフォルト値ですでに保存されている値を上書きするのではなく、ユーザーが実際に設定した値のみを更新することができます。
    4.  保存されているモデルのコピーを作成し、受け取った部分的な更新で属性を更新します（updateパラメータを使用します）。
    5.  コピーしたモデルをDBに保存できるものに変換します（例えば、jsonable_encoderを使用します）。
        これはモデルの.dict()メソッドを再度利用することに匹敵しますが、値をJSONに変換できるデータ型、例えばdatetimeをstrに変換します。
    6.  データをDBに保存します。
    7.  更新されたモデルを返します。
    """
    stored_card_data = cards[card_id]
    stored_card_model = Card(**stored_card_data)
    # デフォルト値の除外
    update_data = card.model_dump(exclude_unset=True)
    # 更新するデータの抽出
    updated_card = stored_card_model.model_copy(update=update_data)
    # モデル更新
    cards[card_id] = jsonable_encoder(updated_card)
    return updated_card


@app.get(
    "/players/",
    response_model=Player,
    tags=["players"],
    summary="Read an Players",
    description="Read an players with all the information, name, description, price, tax and a set of unique tags",
)
async def read_players():
    return [{"player_name": "John Do"}]


@app.get("/players/")
def update_player(id: int, player: Player):
    """
    リクエストボディとしてではなく、単純にJSONとして受け取りたい場合はjsonable_encoderに通す
    この場合はPlayerクラスに則ったリクエストボディ自体はdictへと変換され、last_buyはdatetimeではなく、strへと変換される。
    jsonable_encoderに通した場合、json.dumpでエンコードも可能。
    """
    json_compatible_player_data = jsonable_encoder(player)
    return json.dump(json_compatible_player_data)


# 依存性注入について(クラスで考える)
class CommonQueryParams:
    def __init__(self, q: Union[str, None] = None, skip: int = 0, limit: int = 100):
        self.q = q
        self.skip = skip
        self.limit = limit


fake_samples_db = [{"item_name": "Foo"}, {"item_name": "Bar"}, {"item_name": "Baz"}]


# DependsでクラスをDIする。型付けをしているのでDependsの引数は省略可
@app.get("/di_sample/")
async def read_di_sample(commons: CommonQueryParams = Depends()):
    """DIしたクラスによって関数の引数で自動的にクエリパラメータ、デフォルト値を受け取れる"""
    response = {}
    if commons.q:
        response.update({"q": commons.q})
    samples = fake_samples_db[commons.skip : commons.skip + commons.limit]
    response.update({"samples": samples})


# DIに関してはDB接続の例が一番わかりやすい
def fake_db_conn():
    # データベースの接続情報を設定
    DATABASE_URL = "postgresql://username:password@localhost/database_name"
    # データベースエンジンを作成
    engine = create_engine(DATABASE_URL)
    # セッションファクトリを作成
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    return Session


# DB接続をDIすることで内部で再度かかなくてもよい
def get_db(fake_db_conn: Session = Depends(fake_db_conn)):

    db = fake_db_conn
    try:
        yield db
    finally:
        db.close()


# APIにさらにDIする。これでPOSTやPUT等増えても接続は同じようにDIしてあげれば処理ごとに接続をかかなくてもよい
# DIをネストさせた場合(1回のpathオペレーション、大雑把には1回のAPIリクエストと置き換えてもよし)はDIされる値に対し、キャッシュが働く
# =同じリクエストに対して依存関係を何度も呼び出す代わりに、特定のリクエストでそれを必要とする全ての「依存関係」に渡す
# キャッシュを無効にしたい場合はuse_cache=Falseを関数に指定する
@app.get("/fake_db_conn/")
async def read_fake_db(db: Session = Depends(get_db)):
    items = db.query(Item).all()
    return items


# # アプリ全体にDIを持たせたい場合は以下のようにする
# async def verify_token(x_token: Annotated[str, Header()]):
#     if x_token != "fake-super-secret-token":
#         raise HTTPException(status_code=400, detail="X-Token header invalid")


# async def verify_key(x_key: Annotated[str, Header()]):
#     if x_key != "fake-super-secret-key":
#         raise HTTPException(status_code=400, detail="X-Key header invalid")
#     return x_key


# app = FastAPI(dependencies=[Depends(verify_token), Depends(verify_key)])


# DIに例外が絡むときは注意する
data = {
    "plumbus": {"description": "Freshly pickled plumbus", "owner": "Morty"},
    "portal-gun": {"description": "Gun to create portals", "owner": "Rick"},
}


class OwnerError(Exception):
    pass


def get_username():
    """DIに例外を仕込む場合は、別のHTTPExceptionなどを発生させるのでなければ、except側でもraiseを仕込み、依存先で元の例外を発生させ直す"""
    try:
        yield "Rick"
    except InternalError:
        print("We don't swallow the internal error here, we raise again 😎")
        # ここでraiseしないと依存先で例外が発生した場合、正しく例外をキャッチできない(以下の例だと404エラーではなく、500エラーとなってしまう)
        raise


# NOTE: 1.PathOperation 2. DI(この場合get_username()でユーザー名の取得を行う)  3. 失敗した場合はDIで例外処理(この例であれば500エラーか詳細にやるならカスタム例外を作成し、Connection Errorとするか)
# NOTE: 4. 2が成功した場合、API処理。例外が発生した場合はAPIでの例外処理に基づいてraise
@app.get("/sample2/{id}")
async def get_sample2(data_id: str, username: Annotated[str, Depends(get_username)]):
    if data_id == "portal-gun":
        raise InternalError(
            f"The portal gun is too dangerous to be owned by {username}"
        )
    if data_id != "plumbus":
        raise HTTPException(
            status_code=404, detail="Item not found, there`s only a plumbus here"
        )
    return data_id


class OauthUser(BaseModel):
    username: str
    email: Optional[str] = None
    full_name: Optional[str] = None
    disabled: Optional[bool] = None


class OauthUserInDB(OauthUser):
    hashed_password: str


class Token(BaseModel):
    access_token: str
    token_type: str


class TokenData(BaseModel):
    username: Optional[str] = None


# 暗号化の形式
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


# 処理順4。パスワード認証
def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hashed(password):
    return pwd_context.hash(password)


# 処理2。ユーザー認証
def authenticate_user(fake_db, username: str, password: str):
    user = get_oauth_user(fake_db, username)
    if not user:
        return False
    if not verify_password(password, user.hashed_password):
        return False
    return user


# 処理順5。トークン生成
def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


# 処理順3・9。ユーザー取得
def get_oauth_user(db, username: str):
    if username in db:
        user_dict = db[username]
        return OauthUserInDB(**user_dict)


def fake_decode_token(token):
    user = get_oauth_user(fake_users_db, token)
    return user


def fake_hash_password(password: str):
    return "fakehashed" + password


# 処理順8。アクティブユーザー取得実態。Tokenは型としてoauth2_schemeをDIされパースされる
async def get_current_user(token: str = Depends(oauth2_scheme)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid authentication credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=ALGORITHM)
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
        token_data = TokenData(username=username)
    except InvalidTokenError:
        raise credentials_exception
    user = get_oauth_user(fake_users_db, username=token_data.username)
    if user is None:
        raise credentials_exception
    return user


# 処理順7。アクティブとなるユーザー取得
async def get_current_active_user(
    current_user: Annotated[User, Depends(get_current_user)]
):
    if current_user.disabled:
        raise HTTPException(status_code=400, detail="Inactive user")
    return current_user


# 処理1
@app.post("/token")
async def login_for_access_token(
    form_data: OAuth2PasswordRequestForm = Depends(),
) -> Token:
    user = authenticate_user(fake_users_db, form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    # jwtのsub属性はトークンの内容の識別子として使える(ここではユーザー名をプレフィックスとしてつけている)
    access_token = create_access_token(
        data={"sub": user.username}, expires_delta=access_token_expires
    )
    return Token(access_token=access_token, token_type="bearer")


# 処理順6
@app.get("/o_users/me")
async def read_oauth_users_me(
    current_user: Annotated[OauthUser, Depends(get_current_active_user)]
):
    return current_user


# 処理順10。認証に基づいてユーザーに紐ついた情報を取得
@app.get("/o_users/me/items/")
async def read_own_items(current_user: User = Depends(get_current_active_user)):
    return [{"item_id": "Foo", "owner": current_user.username}]


# DB・SQL。まずモデルを作る
class HeroBase(SQLModel):
    name: str = Field(index=True)
    age: int | None = Field(default=None, index=True)


# table=Trueはテーブルモデル。これがないとデータモデルの扱いになるので注意(テーブルが作成されない)
class Hero(HeroBase, table=True):
    id: int | None = Field(default=None, primary_key=True)
    secret_name: str


# APIクライアントに返すためのデータモデル。シリアライザ用
class HeroPublic(HeroBase):
    id: int


# DBに新しいヒーローを登録するためのデータモデル
class HeroCreate(HeroBase):
    secret_name: str


# Update用のデータモデル。PUT用にすべてOptionalにしておく
class HeroUpdate(HeroBase):
    name: str | None = None
    age: int | None = None
    secret_name: str | None = None


# SQLModelからテーブルを作成する
def create_db_and_tables():
    SQLModel.metadata.create_all(engine)


def get_session():
    with Session(engine) as session:
        yield session


SessionDep = Annotated[Session, Depends(get_session)]


@asynccontextmanager
async def lifespan():
    create_db_and_tables()


# HeroPublicに基づいてシリアライズする。関数の型定義はresponse_model=HeroPublicで省略
@app.post("/heroes/", response_model=HeroPublic)
def create_hero(hero: HeroCreate, session: SessionDep):
    db_hero = Hero.model_validate(hero)
    session.add(db_hero)
    session.commit()
    session.refresh(db_hero)
    return db_hero


@app.get("/heroes/", response_model=list[HeroPublic])
def read_heroes(
    session: SessionDep, offset: int = 0, limit: Annotated[int, Query(le=100)] = 100
) -> list[Hero]:
    heroes = session.exec(select(Hero).offset(offset).limit(limit).all())
    return heroes


@app.get("/heroes/{hero_id}", response_model=HeroPublic)
def read_hero(hero_id: int, session: SessionDep):
    hero = session.get(Hero, hero_id)
    if not hero:
        raise HTTPException(status_code=404, detail="Hero not found")
    return hero


@app.patch("/heroes/{hero_id}", response_model=HeroPublic)
def update_hero(hero_id: int, hero: HeroUpdate, session: SessionDep):
    hero_db = session.get(Hero, hero_id)
    if not hero_db:
        raise HTTPException(status_code=404, detail="Hero not found")
    hero_data = hero.model_dump(exclude_unset=True)
    hero_db.sqlmodel_update(hero_data)
    session.add(hero_db)
    session.commit()
    session.refresh(hero_db)
    return hero_db


@app.delete("/heroes/{hero_id}")
def delete_hero(hero_id: int, session: SessionDep):
    hero = session.get(Hero, hero_id)
    if not hero:
        raise HTTPException(status_code=404, detail="Hero not found")
    session.delete(hero)
    session.commit()
    return {"ok": True}
