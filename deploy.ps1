# Quick Deployment Script for NSE F&O Scanner
# Run this to deploy to your chosen platform

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "   NSE F&O Scanner - Quick Deploy" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

Write-Host "Choose deployment platform:" -ForegroundColor Yellow
Write-Host "1. Render.com (Recommended - Free)" -ForegroundColor Green
Write-Host "2. Vercel (Serverless - Free)" -ForegroundColor Green
Write-Host "3. Railway.app (Easy - Free)" -ForegroundColor Green
Write-Host "4. Heroku (Reliable)" -ForegroundColor Green
Write-Host ""

$choice = Read-Host "Enter choice (1-4)"

switch ($choice) {
    "1" {
        Write-Host "`nDeploying to Render.com..." -ForegroundColor Cyan
        Write-Host "Step 1: Pushing to GitHub..." -ForegroundColor Yellow
        git add .
        git commit -m "Deploy to Render"
        git push origin main
        
        Write-Host "`nStep 2: Manual steps required:" -ForegroundColor Yellow
        Write-Host "1. Go to https://render.com/" -ForegroundColor White
        Write-Host "2. Click 'New +' -> 'Web Service'" -ForegroundColor White
        Write-Host "3. Connect your GitHub repository" -ForegroundColor White
        Write-Host "4. Add environment variables:" -ForegroundColor White
        Write-Host "   ANGEL_API_KEY=your_key" -ForegroundColor Gray
        Write-Host "   ANGEL_CLIENT_ID=your_id" -ForegroundColor Gray
        Write-Host "   ANGEL_PASSWORD=your_password" -ForegroundColor Gray
        Write-Host "   ANGEL_TOTP_SECRET=your_secret" -ForegroundColor Gray
        Write-Host "5. Click 'Create Web Service'" -ForegroundColor White
        Write-Host "`nYour live link will be: https://nse-fo-scanner.onrender.com" -ForegroundColor Green
    }
    
    "2" {
        Write-Host "`nDeploying to Vercel..." -ForegroundColor Cyan
        
        # Check if Vercel CLI is installed
        $vercelInstalled = Get-Command vercel -ErrorAction SilentlyContinue
        if (-not $vercelInstalled) {
            Write-Host "Vercel CLI not found. Installing..." -ForegroundColor Yellow
            npm install -g vercel
        }
        
        Write-Host "Running Vercel deploy..." -ForegroundColor Yellow
        vercel
        
        Write-Host "`nNow add environment variables:" -ForegroundColor Yellow
        Write-Host "vercel env add ANGEL_API_KEY" -ForegroundColor Gray
        Write-Host "vercel env add ANGEL_CLIENT_ID" -ForegroundColor Gray
        Write-Host "vercel env add ANGEL_PASSWORD" -ForegroundColor Gray
        Write-Host "vercel env add ANGEL_TOTP_SECRET" -ForegroundColor Gray
        
        Write-Host "`nThen deploy to production:" -ForegroundColor Yellow
        Write-Host "vercel --prod" -ForegroundColor Gray
    }
    
    "3" {
        Write-Host "`nDeploying to Railway.app..." -ForegroundColor Cyan
        Write-Host "Step 1: Pushing to GitHub..." -ForegroundColor Yellow
        git add .
        git commit -m "Deploy to Railway"
        git push origin main
        
        Write-Host "`nStep 2: Manual steps required:" -ForegroundColor Yellow
        Write-Host "1. Go to https://railway.app/" -ForegroundColor White
        Write-Host "2. Sign up with GitHub" -ForegroundColor White
        Write-Host "3. Click 'New Project' -> 'Deploy from GitHub'" -ForegroundColor White
        Write-Host "4. Add environment variables in Variables tab" -ForegroundColor White
        Write-Host "5. Generate domain in Settings" -ForegroundColor White
        Write-Host "`nYour live link will be: https://your-app.up.railway.app" -ForegroundColor Green
    }
    
    "4" {
        Write-Host "`nDeploying to Heroku..." -ForegroundColor Cyan
        
        # Check if Heroku CLI is installed
        $herokuInstalled = Get-Command heroku -ErrorAction SilentlyContinue
        if (-not $herokuInstalled) {
            Write-Host "Heroku CLI not found. Please install from:" -ForegroundColor Red
            Write-Host "https://devcenter.heroku.com/articles/heroku-cli" -ForegroundColor Yellow
            exit
        }
        
        Write-Host "Creating Heroku app..." -ForegroundColor Yellow
        heroku create nse-fo-scanner
        
        Write-Host "`nSetting environment variables..." -ForegroundColor Yellow
        $apiKey = Read-Host "Enter ANGEL_API_KEY"
        $clientId = Read-Host "Enter ANGEL_CLIENT_ID"
        $password = Read-Host "Enter ANGEL_PASSWORD" -AsSecureString
        $totpSecret = Read-Host "Enter ANGEL_TOTP_SECRET"
        
        heroku config:set ANGEL_API_KEY=$apiKey
        heroku config:set ANGEL_CLIENT_ID=$clientId
        heroku config:set ANGEL_PASSWORD=$password
        heroku config:set ANGEL_TOTP_SECRET=$totpSecret
        
        Write-Host "`nDeploying to Heroku..." -ForegroundColor Yellow
        git push heroku main
        
        Write-Host "`nYour live link: https://nse-fo-scanner.herokuapp.com" -ForegroundColor Green
    }
    
    default {
        Write-Host "Invalid choice. Please run the script again." -ForegroundColor Red
    }
}

Write-Host "`n========================================" -ForegroundColor Cyan
Write-Host "   Deployment Complete!" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
