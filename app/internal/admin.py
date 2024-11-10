from fastapi import APIRouter

# routerのカスタマイズは呼び出し先でオーバーライドすることができる(なのでここでやらなくてもよい、ただしグローバルな設定はやっておくべきだろう)
router = APIRouter()

@router.post("/")
async def update_admin():
  return {"message": "Admin getting Schwifty"}
