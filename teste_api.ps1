$ErrorActionPreference = "Stop"
$backend = "https://dls-auto-pecas-api.onrender.com"

function Post-Json($url, $obj, $headers) {
    $json  = $obj | ConvertTo-Json -Depth 6
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($json)
    return Invoke-RestMethod -Uri $url -Method Post -Body $bytes `
        -ContentType "application/json; charset=utf-8" -Headers $headers
}

Write-Host "`n=== 1. Acordando o backend (pode levar ate 60s) ===" -ForegroundColor Cyan
$inicio = Get-Date
try { Invoke-RestMethod -Uri "$backend/api/v1/products/" -TimeoutSec 120 | Out-Null }
catch { Write-Host "Falhou: $($_.Exception.Message)" -ForegroundColor Red; exit }
Write-Host ("Backend respondeu em {0:N1} segundos" -f ((Get-Date) - $inicio).TotalSeconds)

Write-Host "`n=== 2. Login de administrador ===" -ForegroundColor Cyan
$usuario = Read-Host "admin"
$senhaSS = Read-Host "admin" -AsSecureString
$senha = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
    [Runtime.InteropServices.Marshal]::SecureStringToBSTR($senhaSS))

try {
    $tok  = Post-Json "$backend/api/v1/auth/token/" @{ username = $usuario; password = $senha } $null
    $auth = @{ Authorization = "Bearer $($tok.access)" }
    $me   = Invoke-RestMethod -Uri "$backend/api/v1/auth/me/" -Headers $auth
    Write-Host "Login OK." -ForegroundColor Green
    Write-Host ("  username     : {0}" -f $me.username)
    Write-Host ("  is_staff     : {0}" -f $me.is_staff)
    Write-Host ("  is_superuser : {0}" -f $me.is_superuser)
} catch {
    Write-Host "Login falhou: $($_.Exception.Message)" -ForegroundColor Red
    $auth = $null
}

Write-Host "`n=== 3. Catalogo de produtos ===" -ForegroundColor Cyan
$prods = Invoke-RestMethod -Uri "$backend/api/v1/products/"
Write-Host ("Total cadastrado: {0}" -f $prods.count)
$prods.results | Select-Object sku, name, price, stock, id | Format-Table -AutoSize

Write-Host "`n=== 4. Dimensoes e peso (origem do erro de frete) ===" -ForegroundColor Cyan
$semPeso = 0
foreach ($p in $prods.results) {
    $d = Invoke-RestMethod -Uri "$backend/api/v1/products/$($p.id)/"
    $alerta = ""
    if ([double]$d.weight_kg -le 0) { $alerta = "  <== SEM PESO"; $semPeso++ }
    Write-Host ("{0,-14} peso={1,-8} C={2,-6} L={3,-6} A={4,-6}{5}" -f `
        $d.sku, $d.weight_kg, $d.length_cm, $d.width_cm, $d.height_cm, $alerta)
}
if ($semPeso -gt 0) {
    Write-Host "$semPeso produto(s) sem peso. Isso bloqueia o frete do carrinho inteiro." -ForegroundColor Red
}

Write-Host "`n=== 5. Cotacao de frete (CEP destino 01310-100) ===" -ForegroundColor Cyan
$produtoId = Read-Host "Cole o id de um produto COM peso cadastrado"
try {
    $opcoes = Post-Json "$backend/api/v1/orders/shipping/simulate/" @{
        zip_code = "01310100"
        items    = @(@{ product_id = $produtoId; quantity = 1 })
    } $null
    $opcoes | Format-Table service_id, service, company, price, deadline_days -AutoSize
} catch {
    $r = $_.Exception.Response
    if ($r) {
        $txt = (New-Object IO.StreamReader($r.GetResponseStream())).ReadToEnd()
        Write-Host "HTTP $([int]$r.StatusCode): $txt" -ForegroundColor Red
    } else { Write-Host $_.Exception.Message -ForegroundColor Red }
}

Write-Host "`n=== 6. Pedidos existentes ===" -ForegroundColor Cyan
if ($auth) {
    $peds = Invoke-RestMethod -Uri "$backend/api/v1/orders/" -Headers $auth
    Write-Host ("Total: {0}" -f $peds.count)
    $peds.results | Select-Object id, customer_name, status_display, shipping_fee, total, created_at |
        Format-Table -AutoSize
} else { Write-Host "Pulado: login falhou." -ForegroundColor Yellow }

Write-Host "`n=== Fim ===" -ForegroundColor Cyan