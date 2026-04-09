from django.contrib.auth.views import LogoutView
from django.urls import path

from . import views

urlpatterns = [
    path('', views.CustomLoginView.as_view(), name='login'),
    path('signup/', views.SignUpView.as_view(), name='signup'),
    path('logout/', LogoutView.as_view(next_page='login'), name='logout'),

    path('dashboard/', views.dashboard, name='dashboard'),

    path('objects/', views.ObjectList.as_view(), name='object_list'),
    path('objects/new/', views.ObjectCreate.as_view(), name='object_create'),
    path('objects/<int:pk>/edit/', views.ObjectUpdate.as_view(), name='object_update'),
    path('objects/<int:pk>/delete/', views.ObjectDelete.as_view(), name='object_delete'),

    path('material-groups/', views.MaterialGroupList.as_view(), name='materialgroup_list'),
    path('material-groups/new/', views.MaterialGroupCreate.as_view(), name='materialgroup_create'),
    path('material-groups/<int:pk>/edit/', views.MaterialGroupUpdate.as_view(), name='materialgroup_update'),

    path('reservations/', views.ReservationList.as_view(), name='reservation_list'),
    path('reservations/new/', views.ReservationCreate.as_view(), name='reservation_create'),

    path('suppliers/', views.SupplierList.as_view(), name='supplier_list'),
    path('suppliers/new/', views.SupplierCreate.as_view(), name='supplier_create'),
    path('suppliers/<int:pk>/edit/', views.SupplierUpdate.as_view(), name='supplier_update'),
    path('suppliers/<int:pk>/delete/', views.SupplierDelete.as_view(), name='supplier_delete'),

    path('products/', views.ProductList.as_view(), name='product_list'),
    path('products/new/', views.ProductCreate.as_view(), name='product_create'),
    path('products/<int:pk>/edit/', views.ProductUpdate.as_view(), name='product_update'),
    path('products/<int:pk>/delete/', views.ProductDelete.as_view(), name='product_delete'),
    path('products/set-price/', views.product_set_price, name='product_set_price'),
    path('api/product-price/<int:product_id>/', views.product_price_api, name='product_price_api'),

    path('locations/', views.LocationList.as_view(), name='location_list'),
    path('locations/new/', views.LocationCreate.as_view(), name='location_create'),
    path('locations/<int:pk>/edit/', views.LocationUpdate.as_view(), name='location_update'),
    path('locations/<int:pk>/delete/', views.LocationDelete.as_view(), name='location_delete'),

    path('stock/', views.StockList.as_view(), name='stock_list'),
    path('moves/', views.StockMoveList.as_view(), name='stockmove_list'),
    path('moves/new/', views.stockmove_create, name='stockmove_create'),

    path('po/', views.POList.as_view(), name='po_list'),
    path('po/new/', views.po_create, name='po_create'),
    path('po/<int:pk>/edit/', views.po_edit, name='po_edit'),
    path('po/<int:pk>/export/docx/', views.po_export_docx, name='po_export_docx'),
    path('po/<int:pk>/export/pdf/', views.po_export_pdf, name='po_export_pdf'),
    path('po/<int:pk>/delete/', views.po_delete, name='po_delete'),

    path('supply-requests/', views.SupplyRequestList.as_view(), name='supplyrequest_list'),
    path('supply-requests/new/', views.supply_request_create, name='supplyrequest_create'),
    path('supply-requests/<int:pk>/', views.SupplyRequestDetail.as_view(), name='supplyrequest_detail'),
    path('supply-requests/<int:pk>/add-item/', views.supply_request_add_item, name='supplyrequest_add_item'),
    path('supply-requests/<int:pk>/edit-item/<int:item_pk>/', views.supply_request_edit_item, name='supplyrequest_edit_item'),
    path('supply-requests/<int:pk>/delete-item/<int:item_pk>/', views.supply_request_delete_item, name='supplyrequest_delete_item'),
    path('supply-requests/<int:pk>/update-status/', views.supply_request_update_status, name='supplyrequest_update_status'),
    path('supply-requests/<int:pk>/delete/', views.supply_request_delete, name='supplyrequest_delete'),
    path('supply-requests/<int:pk>/print/', views.supply_request_print, name='supplyrequest_print'),

    path('picks/', views.PickTaskList.as_view(), name='picktask_list'),
    path('picks/new/', views.picktask_create, name='picktask_create'),
    path('picks/<int:pk>/', views.PickTaskDetail.as_view(), name='picktask_detail'),
    path('picks/<int:pk>/complete/', views.picktask_complete, name='picktask_complete'),

    path('api/check-reservation/', views.check_reservation_api, name='check_reservation_api'),
    path('api/product-batches/', views.product_batches_api, name='product_batches_api'),
]
