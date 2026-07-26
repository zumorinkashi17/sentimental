from django.shortcuts import render


def list_view(request):
    return render(request, 'callers/list.html')


def database_view(request):
    return render(request, 'callers/database.html')
