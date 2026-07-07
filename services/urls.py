from django.urls import path
from . import views
from . import reloadly_views as rl

urlpatterns = [
    # ── Reloadly: Airtime / Data ──
    path('airtime/countries/', rl.AirtimeCountriesView.as_view(), name='airtime-countries'),
    path('airtime/detect/', rl.AirtimeDetectView.as_view(), name='airtime-detect'),
    path('airtime/operators/', rl.AirtimeOperatorsView.as_view(), name='airtime-operators'),
    path('airtime/purchase/', rl.AirtimePurchaseView.as_view(), name='airtime-purchase'),
    path('airtime/orders/', rl.AirtimeOrdersView.as_view(), name='airtime-orders'),
    # ── Reloadly: Gift Cards ──
    path('giftcards/countries/', rl.GiftCardCountriesView.as_view(), name='giftcard-countries'),
    path('giftcards/', rl.GiftCardProductsView.as_view(), name='giftcard-products'),
    path('giftcards/purchase/', rl.GiftCardPurchaseView.as_view(), name='giftcard-purchase'),
    path('giftcards/orders/', rl.GiftCardOrdersView.as_view(), name='giftcard-orders'),
    path('giftcards/orders/<int:order_id>/refresh/', rl.GiftCardRefreshView.as_view(), name='giftcard-refresh'),
    # ── Reloadly: Utility Bills ──
    path('utilities/countries/', rl.UtilityCountriesView.as_view(), name='utility-countries'),
    path('utilities/billers/', rl.UtilityBillersView.as_view(), name='utility-billers'),
    path('utilities/pay/', rl.UtilityPayView.as_view(), name='utility-pay'),
    path('utilities/orders/', rl.UtilityOrdersView.as_view(), name='utility-orders'),

    path('countries/', views.CountriesView.as_view(), name='countries'),
    path('products/<str:country>/', views.ProductsView.as_view(), name='products'),
    path('prices/', views.PricesByProductView.as_view(), name='prices-by-product'),
    path('catalog/', views.ServiceCatalogView.as_view(), name='service-catalog'),
    # Temporary Email (mail.tm)
    path('email/create/', views.TempEmailCreateView.as_view(), name='email-create'),
    path('email/<int:order_id>/inbox/', views.TempEmailInboxView.as_view(), name='email-inbox'),
    path('email/<int:order_id>/message/<str:message_id>/', views.TempEmailMessageView.as_view(), name='email-message'),
    path('email/<int:order_id>/delete/', views.TempEmailDeleteView.as_view(), name='email-delete'),
    # Residential Proxies (Bright Data)
    path('proxy/purchase/', views.ProxyPurchaseView.as_view(), name='proxy-purchase'),
    path('proxy/<int:order_id>/', views.ProxyOrderDetailView.as_view(), name='proxy-detail'),
    # Bulk SMS (Twilio)
    path('sms/buy/', views.SMSBuyCreditsView.as_view(), name='sms-buy'),
    path('sms/send/', views.SMSSendView.as_view(), name='sms-send'),
    path('sms/orders/', views.SMSOrdersView.as_view(), name='sms-orders'),
    # Phone Number Lookup (Twilio)
    path('lookup/buy/', views.LookupBuyView.as_view(), name='lookup-buy'),
    path('lookup/run/', views.LookupView.as_view(), name='lookup-run'),
    path('lookup/orders/', views.LookupOrdersView.as_view(), name='lookup-orders'),
    # eSIM (ESIMCard)
    path('esim/countries/', views.ESIMCountriesView.as_view(), name='esim-countries'),
    path('esim/packages/<int:country_id>/', views.ESIMCountryPackagesView.as_view(), name='esim-packages'),
    path('esim/purchase/', views.ESIMPurchaseView.as_view(), name='esim-purchase'),
    path('esim/orders/', views.ESIMOrdersView.as_view(), name='esim-orders'),
    path('esim/orders/<int:order_id>/', views.ESIMOrderDetailView.as_view(), name='esim-order-detail'),
    path('esim/orders/<int:order_id>/refresh/', views.ESIMRefreshView.as_view(), name='esim-refresh'),
    # TigerSMS (virtual number countries & products)
    path('tiger/countries/', views.TigerCountriesView.as_view(), name='tiger-countries'),
    path('tiger/products/<str:country>/', views.TigerProductsView.as_view(), name='tiger-products'),
    # Debug: see raw TigerSMS response — remove after confirming format
    path('tiger/debug/<str:country>/', views.TigerProductsView.as_view(), name='tiger-debug'),
    # GrizzlySMS (primary virtual number provider + OTP)
    path('grizzly/countries/', views.GrizzlyCountriesView.as_view(), name='grizzly-countries'),
    path('grizzly/products/<str:country>/', views.GrizzlyProductsView.as_view(), name='grizzly-products'),
    path('grizzly/catalog/', views.GrizzlyOTPCatalogView.as_view(), name='grizzly-catalog'),
    path('grizzly/prices/', views.GrizzlyOTPPricesView.as_view(), name='grizzly-prices'),
    # WireGuard VPN
    path('vpn/plans/', views.VPNPlansView.as_view(), name='vpn-plans'),
    path('vpn/purchase/', views.VPNPurchaseView.as_view(), name='vpn-purchase'),
    path('vpn/orders/', views.VPNOrdersView.as_view(), name='vpn-orders'),
    path('vpn/orders/<int:order_id>/', views.VPNOrderDetailView.as_view(), name='vpn-order-detail'),
    path('vpn/orders/<int:order_id>/download/', views.VPNConfigDownloadView.as_view(), name='vpn-config-download'),
    path('vpn/orders/<int:order_id>/cancel/', views.VPNCancelView.as_view(), name='vpn-cancel'),
]