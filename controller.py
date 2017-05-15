# -*- coding: utf-8 -*-

from openerp.addons.web import http
import json
from openerp.modules.registry import RegistryManager
from openerp.osv.osv import except_osv
from werkzeug.wrappers import Response


TOKEN = 'XXXXXXXXXXXXXXXXXXXXXXXXXXXXX'

def check_token(fn):
    def wrapped(self, request):
        if 'token' in request.params and request.params['token'] == TOKEN:
            return fn(self, request)
        return '403 FORBIDDEN. INVALID TOKEN'

    return wrapped


def check_param_table(fn):
    def wrapped(self, request):
        if 'table' in request.params:
            if ServiceAPI.check_perm_table(request.params['table']):
                return fn(self, request)
        return '403 FORBIDDEN. PERMISSION DENIED'

    return wrapped


class ServiceAPI(http.Controller):
    _cp_path = '/api'

    default_database = '16_09_02_tgt'

    @staticmethod
    def check_perm_table(table_name):
        return table_name in ALLOWED_TABLES or '.' in table_name

    @staticmethod
    def filter_ids(cr, table_pool, ids):
        "Filter ids using filters"
        filters = FILTERS.get(table_pool.name, [])
        if not filters:
            return ids
        filtered_ids = table_pool.search(cr, API_UID, filters)
        filtered_ids = set(ids) & set(filtered_ids)
        return list(filtered_ids)

    @staticmethod
    def filter_update(cr, table_pool, objs):
        "Update obj using filters"
        filters = FILTERS.get(table_pool.name, [])
        if not filters:
            return objs
        # update every obj in objects (dict of values) using filters' values
        map(lambda obj: obj.update({filter[0]: filter[2] for filter in filters}), objs)

    @http.httprequest
    @check_token
    @check_param_table
    def get_fields_info(self, request, **kwargs):
        """
       Request with param 'table' and return list of fields
       ===
       REQUEST
       :param table - string
       ===
       RESPONSE
       [{'name': 'name_id', 'type': 'many2one', 'obj': 'module_name.resource.string'}, ...]
       """
        table_name = request.params['table']
        registry = RegistryManager.get(self.default_database)
        table_pool = registry.get(table_name)
        # формируем список полей в виде словарей
        table_fields = [{'name': field_name, 'type': field_obj._type, 'obj': field_obj._obj or {}} \
                        for field_name, field_obj in table_pool._columns.iteritems()]
        response = json.dumps(table_fields)
        return response

    @http.httprequest
    @check_token
    def get_list_models(self, request, **kwargs):
        """
       Return a list of models
       ===
       REQUEST
       :params none (only token)
       ===
       RESPONSE
       ['module_name.resource.string', 'module_name.unit', 'module_name.sensor', ...]
       """
        registry = RegistryManager.get(self.default_database)
        with registry.cursor() as cr:
            model_pool = registry.get('ir.model')
            show_models = []
            ids = model_pool.search(cr, API_UID,
                                    [('model', 'like', 'module_name.')])  # проходим по моделькам с названиемями module_name.*
            for model in model_pool.browse(cr, API_UID, ids):
                if 'module_name' in model.modules:  # доп проверка что он в модуле module_name
                    show_models.append(model.model)
            show_models.extend(ALLOWED_TABLES)  # доп таблицы из других модулей
            response = json.dumps(show_models)
            return response

    @http.httprequest
    @check_token
    @check_param_table
    def service_update(self, request, **kwargs):
        """
       Edit existing objects
       ===
       REQUEST
       :param table - string
       :param data - json (example:
       [{'id': 10, 'name': 'QQQ-15', 'tool_id': 15}, {'id': 11, 'name': 'QWE-123', 'tool_id': 30, 'price': 50}]
       )
       ===
       RESPONSE
       True/Error
       [True, "Error: object with this id not found"]
       """
        try:
            data = request.params['data']
        except KeyError:
            return "Wrong arguments"
        table_name = request.params['table']
        registry = RegistryManager.get(self.default_database)
        with registry.cursor() as cr:
            table_pool = registry.get(table_name)
            table_fields = self.get_fields_info(request, **kwargs)  # информация о существующих полях в таблице
            table_fields = {f['name'] for f in json.loads(table_fields)}
            ids = [obj.id for obj in data]  # вытаскиваем все айдишники
            filtered_ids = ServiceAPI.filter_ids(cr, table_pool, ids)  # и фильтруем
            data = json.loads(data)
            res = []
            for obj in data:
                if not 'id' in obj:  # айдишник при создании указываться не должен
                    res.append('arg "id" should be')
                    continue
                if obj['id'] not in filtered_ids:  # если указан айдишник вне фильтра, значит ошибка
                    res.append('this id is not allowed')
                    continue
                if not all(field in table_fields for field in obj):  # все ли поля входят в схему модели
                    res.append('wrong fields')
                    continue
                id = obj['id']  # fetch id from obj (values)
                del obj['id']
                try:
                    id_updated = table_pool.write(cr, API_UID, id, obj)
                    res.append(id_updated)
                except except_osv, e:
                    res.append('error: ' + e.name + '; ' + e.value)
        return json.dumps(res)

    @http.httprequest
    @check_token
    @check_param_table
    def service_create(self, request, **kwargs):
        """
       Create objects
       ===
       REQUEST
       :param table - string
       :param data - json (example:
       [{'name': 'QQQ-15', 'tool_id': 15}, {'name': 'QWE-123', 'tool_id': 30, 'price': 50}]
       )
       ===
       RESPONSE
       ids of created objects
       [12, 13]
       """
        try:
            data = request.params['data']
        except KeyError:
            return "Wrong arguments"
        table_name = request.params['table']
        registry = RegistryManager.get(self.default_database)
        with registry.cursor() as cr:
            table_pool = registry.get(table_name)
            table_fields = self.get_fields_info(request, **kwargs)  # информация о существующих полях в таблице
            table_fields = {f['name'] for f in json.loads(table_fields)}
            data = json.loads(data)
            res = []
            ServiceAPI.filter_update(cr, table_pool, data)
            for obj in data:
                if 'id' in obj:  # айдишник при создании указываться не должен
                    res.append('arg "id" is not allowed')
                    continue
                if not all(field in table_fields for field in obj):  # все ли поля входят в схему модели
                    res.append('wrong fields')
                    continue
                try:
                    id_created = table_pool.create(cr, API_UID, obj)
                    res.append(id_created)
                except except_osv, e:
                    res.append('error: ' + e.name + '; ' + e.value)
        return json.dumps(res)

    @http.httprequest
    @check_token
    @check_param_table
    def service_delete(self, request, **kwargs):
        """
       Delete objects
       ===
       REQUEST
       :param table - string
       :param ids - json (example: "[1, 5, 6]")
       ===
       RESPONSE
       True/Error
       """
        try:
            table_name = request.params['table']
            ids = json.loads(request.params['ids'])
        except KeyError:
            return "Wrong arguments"
        registry = RegistryManager.get(self.default_database)
        with registry.cursor() as cr:
            table_pool = registry.get(table_name)
            ids = ServiceAPI.filter_ids(cr, table_pool, ids)
            try:
                table_pool.unlink(cr, API_UID, ids)
            except except_osv, e:
                return "Error: " + e.name + '; ' + e.value
        return True

    @http.httprequest
    @check_token
    def service_get(self, request, **kwargs):
        """
           Return json hierarchy for model
           :param data - json
           examples:
           ===
           REQUEST sample
           'table':
           [
             [ids], <- ids can be empty for all ids
             [field1, fields2, [foreign_fields3, [ fields24]], ... ],
             {
               'alias':
               [
                 'table',
                 'assigned_field',
                 [ fields ... ],
                 {
                 'alias',
                 ...
                 }
               ],
               ... <- you can set new dictionary for new relationships or keep empty or don't set
             }
           ]

           ====
           REQUEST
           'project':
           [
            [3,5],
            ['name']
           ]
           RESPONSE
           [
               {'id': 3, 'name': 'AXC-100'},
               {'id': 5, 'name': 'AQWE-99'},
           ]

           ====
           REQUEST
           'user':
           [
           [100],
           [
             'name',
             ['manager_id',
               [
                 'name',
                 'age'
               ]
             ]
           ]
           ]
           RESPONSE
           [
             {
               'id': 100,
               'name': 'Arkadiy Vasilyev',
               'manager_id':
               {
                 'name': 'Andrey Ivanov',
                 'age': 41
               }
             }
           ]

           ====
           REQUEST
           'project':
           [
             [99],
             ['name'],
             {
               'child_project_ids':
               [
                 'project',
                 'parent_id',
                 ['name'],
                 {}
               ]
             }
           ]
           RESPONSE
           [
           {
             'id': 99,
             'name': 'XWB-32',
             'child_project_ids':
             [
               {
                 'id': 3,
                 'name': 'AXC-100'
               },
               {
                 'id': 5,
                 'name': {}
               }
             ]
           }
           ]

           ====
           REQUEST
           'project':
           [
             [99],
             ['name'],
             {
               'child_project_ids':
               [
                 'project',
                 'parent_id',
                 ['name', 'customer_id': ['name']],
                 {}
               ]
             }
           ]
           RESPONSE
           [
           {
             'id': 99,
             'name': 'XWB-32',
             'child_project_ids':
             [
               {
                 'id': 3,
                 'name': 'AXC-100',
                 'customer_id': {'id': 42, 'name': 'Maksim Mikheev'}
               },
               {
                 'id': 5,
                 'name': 'AQWE-99',
                 'customer_id': {}
               }
             ]
           }
           ]

           ====
           REQUEST
           'user':
           [
             [100],
             [],
             {
               'role_ids':
               [
                 'UserRole',
                 'user_id',
                 [
                   'role_id': ['name']
                 ]
               ]
             }
           ]
           RESPONSE
           [
           {
             'id':100,
             'role_ids':
             [
             {
               'id':  123124,
               'role_id': { 'id': 120, 'name': 'Director'}
             },
             {
                'id': 51244,
                'role_id': { 'id': 100, 'name': 'Sales'}
             }
             ]
           }
           ]

       """

        def recursive_get_data_from_list(obj, fields):
            data = {'id': obj.id}  # айдишник всегда есть у объекта
            for field in fields:
                if isinstance(field, list):
                    # ['table', [fields]] элемент имеет такой вид, значит это many2one
                    try:
                        obj2 = obj[field[0]]  # вытаскиваем объект и...
                    except KeyError:
                        data[field[0]] = None
                        continue
                    data[field[0]] = obj2 and recursive_get_data_from_list(obj2, field[
                        1]) or None  # ...рекурсивно ищем данные
                else:
                    # если обычное поле то просто берём его, везде проверки на KeyError, в этом случае пустой словарь
                    try:
                        data[field] = obj[field]
                    except KeyError:
                        data[field] = None
                        continue
            return data

        def get_tables_data(tables, id=None):
            data = {}
            registry = RegistryManager.get(self.default_database)
            with registry.cursor() as cr:
                for alias, table_info in tables.iteritems():
                    # проходимся по словарю, если это рутовый уровень, то id None, оно будет браться из [ids]
                    # формируем данные
                    if id is None:
                        table_name = alias
                        ids = table_info[0]
                        fields = table_info[1]
                        related_tables = table_info[2]
                        table_pool = registry.get(table_name)
                        # если список айди пустой, значит ищем все
                        if not ids:
                            ids = table_pool.search(cr, API_UID, [])
                    else:
                        table_name = table_info[0]
                        related_field = table_info[1]
                        fields = table_info[2]
                        related_tables = len(table_info) > 3 and table_info[3] or {}
                        table_pool = registry.get(table_name)
                        # если у нас не рутовый уровень, то мы ищем айдишники объекта по связанному полю
                        ids = table_pool.search(cr, API_UID, [(related_field, '=', id)])
                    ids = ServiceAPI.filter_ids(cr, table_pool, ids)  # фильтруем Ids
                    if not ServiceAPI.check_perm_table(table_name):
                        data[alias] = None
                        continue
                    data[alias] = []  # данные для этого алиаса
                    for obj in table_pool.browse(cr, API_UID, ids):
                        table_data = recursive_get_data_from_list(obj, fields)  # рекурсивно вытаскиваем поля у модельки
                        if related_tables:
                            related_tables_data = get_tables_data(related_tables,
                                                                  obj.id)  # рекурсивно связываем другие таблицы (связи one2many и many2many)
                            table_data.update(related_tables_data)
                        data[alias].append(table_data)
            return data

        if not 'data' in request.params:
            return '400 Bad Request'
        json_request = json.loads(request.params['data'])
        response = json.dumps(get_tables_data(json_request))
        return response