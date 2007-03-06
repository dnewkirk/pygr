

from __future__ import generators
from mapping import *
import types
    

class TupleO(object):
    """Provide attribute interface to a tuple.  Subclass this and create _attrcol
    that maps attribute names to tuple index values."""
    def __init__(self,data):
        self.data=data
    def __getattr__(self,attr):
        try:
            return self.data[self._attrcol[attr]]
        except KeyError:
            raise AttributeError('no attribute %s' % attr)


class SQLRow(object):
    """Provide transparent interface to a row in the database: attribute access
       will be mapped to SELECT of the appropriate column, but data is not cached
       on this object.
    """
    def __init__(self,table,id):
        self.db=table
        self.id=id

    def _select(self,what):
        "Get SQL select expression for this row"
        self.db.cursor.execute('select %s from %s where %s=%%s'
                               % (what,self.db.name,self.db.primary_key),(self.id,))
        l=self.db.cursor.fetchall()
        if len(l)!=1:
            raise KeyError('%s[%s].%s not found, or not unique'
                           % (self.db.name,str(self.id),what))
        return l[0][0] # RETURN THE SINGLE FIELD WE REQUESTED

    def __getattr__(self,attr):
        return self._select(self.db._attrSQL(attr))

def ClassicUnpickler(cls, state):
    self = cls.__new__(cls)
    self.__setstate__(state)
    return self
ClassicUnpickler.__safe_for_unpickling__ = 1



class SQLTableBase(dict):
    "Store information about an SQL table as dict keyed by primary key"
    def __init__(self,name,cursor=None,itemClass=None,attrAlias=None,
                 clusterKey=None):
        dict.__init__(self) # INITIALIZE EMPTY DICTIONARY
        if cursor is None:
            import MySQLdb,os
            cursor=MySQLdb.connect(read_default_file=os.environ['HOME']+'/.my.cnf',compress=True).cursor()
        cursor.execute('describe %s' % name)
        columns=cursor.fetchall()
        self.cursor=cursor
        self.name=name
        self.primary_key=None
        self.indexed={}
        self.data={}
        self.description={}
        icol=0
        cursor.execute('select * from %s limit 1' % name)
        for c in columns:
            field=c[0]
            if c[3]=="PRI":
                self.primary_key=field
            elif c[3]=="MUL":
                self.indexed[field]=icol
            self.data[field]=icol
            self.description[field]=cursor.description[icol]
            icol += 1
        if self.primary_key != None: # MAKE PRIMARY KEY ALWAYS ACCESSIBLE AS ATTRIBUTE id
            self.data['id']=self.data[self.primary_key]
        if hasattr(self,'_attr_alias'): # FINALLY, APPLY ANY ATTRIBUTE ALIASES FOR THIS CLASS
            self.addAttrAlias(**self._attr_alias)
        if itemClass is not None or not hasattr(self,'itemClass'):
            self.objclass(itemClass) # NEED TO SET OUR DEFAULT ITEM CLASS
        if attrAlias is not None: # ADD ATTRIBUTE ALIASES
            self.data.update(attrAlias)
        if clusterKey is not None:
            self.clusterKey=clusterKey

    def __reduce__(self): ############################# SUPPORT FOR PICKLING
        return (ClassicUnpickler, (self.__class__,self.__getstate__()))
    def __getstate__(self):
        d=self.getAttrAlias() # SAVE ATTRIBUTE ALIASES
        if self.itemClass.__name__=='foo': # NO NEED TO SAVE ITEM CLASS
            return [self.name,None,None,d]
        else: # SAVE ITEM CLASS
            return [self.name,None,self.itemClass,d]
    def __setstate__(self,l):
        self.__init__(*l)
    def __repr__(self):
        return '<SQL table '+self.name+'>'

    def _attrSQL(self,attr):
        "Translate python attribute name to appropriate SQL expression"
        try: # MAKE SURE THIS ATTRIBUTE CAN BE MAPPED TO DATABASE EXPRESSION
            field=self.data[attr]
        except KeyError:
            raise AttributeError('%s not a valid column in %s' % (attr,self.name))
        if isinstance(field,types.StringType):
            attr=field # USE ALIASED EXPRESSION FOR DATABASE SELECT INSTEAD OF attr
        elif attr=='id':
            attr=self.primary_key
        return attr
    def getAttrAlias(self):
        'get a dict of attribute aliases'
        d={}
        for k,v in self.data.items():
            if isinstance(v,types.StringType):
                d[k]=v
        return d
    def addAttrAlias(self,**kwargs):
        """Add new attributes as aliases of existing attributes.
           They can be specified either as named args:
           t.addAttrAlias(newattr=oldattr)
           or by passing a dictionary kwargs whose keys are newattr
           and values are oldattr:
           t.addAttrAlias(**kwargs)
        """
        for key,val in kwargs.items():
            try: # 1ST TREAT AS ALIAS TO EXISTING COLUMN
                self.data[key]=self.data[val]
            except KeyError: # TREAT AS ALIAS TO SQL EXPRESSION
                self.data[key]=val

    def objclass(self,oclass=None):
        "Specify class for python object representing a row in this table"
        if oclass==None: # DEFAULT: SUBCLASS TupleO TO PROVIDE ATTRIBUTE ACCESS
            class foo(TupleO):
                pass
            oclass=foo
        if issubclass(oclass,TupleO) and not hasattr(oclass,'_attrcol'):
            oclass._attrcol=self.data # BIND ATTRIBUTE LIST TO TUPLEO INTERFACE
        if hasattr(oclass,'_tableclass') and not isinstance(self,oclass._tableclass):
            self.__class__=oclass._tableclass # ROW CLASS CAN OVERRIDE OUR CURRENT TABLE CLASS
        self.itemClass=oclass
    def select(self,whereClause,params=None,oclass=None,selectCols='t1.*'):
        "Generate the list of objects that satisfy the database SELECT"
        if oclass is None:
            oclass=self.itemClass
        self.cursor.execute('select %s from %s t1 %s'
                            % (selectCols,self.name,whereClause),params)
        l=self.cursor.fetchall()
        for t in l:
            yield self.cacheItem(t,oclass)
    def tupleItem(self,t,oclass):
        'create object to represent this row, using oclass'
        o=oclass(t)
        o.db=self # MARK THE OBJECT AS BEING PART OF THIS CONTAINER
        return o
    def getID(self,t): return t[self.data['id']] # GET ID FROM TUPLE
    def cacheItem(self,t,oclass):
        'get obj from cache if possible, or construct from tuple'
        try:
            id=self.getID(t)
        except KeyError: # NO PRIMARY KEY?  IGNORE THE CACHE.
            return self.tupleItem(t,oclass)
        try: # IF ALREADY LOADED IN OUR DICTIONARY, JUST RETURN THAT ENTRY
            return dict.__getitem__(self,id)
        except KeyError:
            pass
        o=self.tupleItem(t,oclass)
        dict.__setitem__(self,id,o)   # CACHE THIS ITEM IN OUR DICTIONARY
        return o


def getKeys(self):
    'uses db select; does not force load'
    self.cursor.execute('select %s from %s' %(self.primary_key,self.name))
    return [t[0] for t in self.cursor.fetchall()] # GET ALL AT ONCE, SINCE OTHER CALLS MAY REUSE THIS CURSOR...


class SQLTable(SQLTableBase):
    "Provide on-the-fly access to rows in the database, caching the results in dict"
    keys=getKeys
    def __iter__(self): return iter(self.keys())
    def load(self,oclass=None):
        "Load all data from the table"
        try: # IF ALREADY LOADED, NO NEED TO DO ANYTHING
            return self._isLoaded
        except AttributeError:
            pass
        if oclass is None:
            oclass=self.itemClass
        self.cursor.execute('select * from %s' % self.name)
        l=self.cursor.fetchall()
        for t in l:
            self.cacheItem(t,oclass) # CACHE IT IN LOCAL DICTIONARY
        self._isLoaded=True # MARK THIS CONTAINER AS FULLY LOADED

    def __getitem__(self,k): # FIRST TRY LOCAL INDEX, THEN TRY DATABASE
        try:
            return dict.__getitem__(self,k) # DIRECTLY RETURN CACHED VALUE
        except KeyError: # NOT FOUND, SO TRY THE DATABASE
            self.cursor.execute('select * from %s where %s=%%s'
                                % (self.name,self.primary_key),(k,))
            l=self.cursor.fetchall()
            if len(l)!=1:
                raise KeyError('%s not found in %s, or not unique' %(str(k),self.name))
            return self.cacheItem(l[0],self.itemClass) # CACHE IT IN LOCAL DICTIONARY
    def items(self):
        'forces load of entire table into memory'
        self.load()
        return dict.items(self)
    def iteritems(self):
        'forces load of entire table into memory'
        self.load()
        return dict.iteritems(self)
    def values(self):
        'forces load of entire table into memory'
        self.load()
        return dict.values(self)
    def itervalues(self):
        'forces load of entire table into memory'
        self.load()
        return dict.itervalues(self)


class SQLTableClustered(SQLTable):
    '''use clusterKey to load a whole cluster of rows at once,
       specifically, all rows that share the same clusterKey value.'''
    def __getstate__(self): # ALSO NEED TO SAVE clusterKey SETTING
        return SQLTableBase.__getstate__(self)+[self.clusterKey]
    def __getitem__(self,k):
        try:
            return dict.__getitem__(self,k) # DIRECTLY RETURN CACHED VALUE
        except KeyError: # NOT FOUND, SO TRY THE DATABASE
            self.cursor.execute('select t2.* from %s t1,%s t2 where t1.%s=%%s and t1.%s=t2.%s'
                                % (self.name,self.name,self.primary_key,
                                   self.clusterKey,self.clusterKey),(k,))
            l=self.cursor.fetchall()
            for t in l: # LOAD THE ENTIRE CLUSTER INTO OUR LOCAL CACHE
                self.cacheItem(t,self.itemClass)
            return dict.__getitem__(self,k) # SHOULD BE IN CACHE, IF ROW k EXISTS


class SQLForeignRelation(object):
    'mapping based on matching a foreign key in an SQL table'
    def __init__(self,table,keyName):
        self.table=table
        self.keyName=keyName
    def __getitem__(self,k):
        'get list of objects o with getattr(o,keyName)==k.id'
        l=[]
        for o in self.table.select('where %s=%%s'%self.keyName,(k.id,)):
            l.append(o)
        if len(l)==0:
            raise KeyError('%s not found in %s' %(str(k),self.name))
        return l


class SQLTableNoCache(SQLTableBase):
    "Provide on-the-fly access to rows in the database, but never cache results"
    itemClass=SQLRow # DEFAULT OBJECT CLASS FOR ROWS...
    keys=getKeys
    def __iter__(self): return iter(self.keys())
    def getID(self,t): return t[0] # GET ID FROM TUPLE
    def select(self,whereClause,params):
        return SQLTableBase.select(self,whereClause,params,self.oclass,
                                   self._attrSQL('id'))
    def oclass(self,t): # CREATE OBJECT FROM TUPLE
        return self.itemClass(self,t[0]) # AN EMPTY CONTAINER FOR ACCESSING THIS ROW
    def __getitem__(self,k): # FIRST TRY LOCAL INDEX, THEN TRY DATABASE
        try:
            return dict.__getitem__(self,k) # DIRECTLY RETURN CACHED VALUE
        except KeyError: # NOT FOUND, SO TRY THE DATABASE
            o=self.itemClass(self,k) # RETURN AN EMPTY CONTAINER FOR ACCESSING THIS ROW
            dict.__setitem__(self,k,o) # STORE EMPTY CONTAINER IN LOCAL DICTIONARY
            return o
    def addAttrAlias(self,**kwargs):
        self.data.update(kwargs) # ALIAS KEYS TO EXPRESSION VALUES

SQLRow._tableclass=SQLTableNoCache  # SQLRow IS FOR NON-CACHING TABLE INTERFACE


class SQLTableMultiNoCache(SQLTableBase):
    "Trivial on-the-fly access for table with key that returns multiple rows"
    _distinct_key='id' # DEFAULT COLUMN TO USE AS KEY
    def __iter__(self):
        self.cursor.execute('select distinct(%s) from %s'
                            %(self._attrSQL(self._distinct_key),self.name))
        l=self.cursor.fetchall() # PREFETCH ALL ROWS, SINCE CURSOR MAY BE REUSED
        for row in l:
            yield row[0]

    def __getitem__(self,id):
        self.cursor.execute('select * from %s where %s=%%s'
                            %(self.name,self._attrSQL(self._distinct_key)),(id,))
        l=self.cursor.fetchall() # PREFETCH ALL ROWS, SINCE CURSOR MAY BE REUSED
        if not hasattr(self,'itemClass'):
            self.objclass() # GENERATE DEFAULT OBJECT CLASS BASED ON TupleO
        for row in l:
            yield self.itemClass(row)
    def addAttrAlias(self,**kwargs):
        self.data.update(kwargs) # ALIAS KEYS TO EXPRESSION VALUES



class SQLEdges(SQLTableMultiNoCache):
    '''provide iterator over edges as (source_id,target_id,edge_id)
       and getitem[edge_id] --> [(source_id,target_id),...]'''
    _distinct_key='edge_id'
    def keys(self):
        self.cursor.execute('select %s,%s,%s from %s'
                            %(self._attrSQL('source_id'),
                              self._attrSQL('target_id'),
                              self._attrSQL('edge_id'),self.name))
        return self.cursor.fetchall() # PREFETCH ALL ROWS, SINCE CURSOR MAY BE REUSED
    __call__=keys
    def __iter__(self):
        for i in self.keys():
            yield i
    def __getitem__(self,id):
        self.cursor.execute('select %s,%s from %s where %s=%%s'
                            %(self._attrSQL('source_id'),
                              self._attrSQL('target_id'),
                              self.name,self._attrSQL(self._distinct_key)),(id,))
        return self.cursor.fetchall() # PREFETCH ALL ROWS, SINCE CURSOR MAY BE REUSED

class SQLEdgeDict(object):
    '2nd level graph interface to SQL database'
    def __init__(self,fromNode,table):
        self.fromNode=fromNode
        self.table=table
    def __getitem__(self,target):
        self.table.cursor.execute('select %s from %s where %s=%%s and %s=%%s'
                                  %(self.table._attrSQL('edge_id'),
                                    self.table.name,self.table._attrSQL('source_id'),
                                    self.table._attrSQL('target_id')),
                                  (self.fromNode,target))
        l=self.table.cursor.fetchall()
        try:
            return l[0][0] # RETURN EDGE
        except IndexError:
            raise KeyError('no edge from node to target')
    def __setitem__(self,target,edge):
        self.table.cursor.execute('insert into %s values (%%s,%%s,%%s)'
                                  %self.table.name,
                                  (self.fromNode,target,edge))
    def __delitem__(self,target):
        if self.table.cursor.execute('delete from %s where %s=%%s and %s=%%s'
                                     %(self.table.name,self.table._attrSQL('source_id'),
                                       self.table._attrSQL('target_id')),
                                     (self.fromNode,target))<1:
            raise KeyError('no edge from node to target')
        
    __iter__=lambda self:self.iteritems(0)
    keys=lambda self:[k for k in self]
    itervalues=lambda self:self.iteritems(1)
    values=lambda self:[k for k in self.iteritems(1)]
    items=lambda self:[k for k in self.iteritems()]
    edges=lambda self:[(self.fromNode,)+k for k in self.iteritems()]
    def iteritems(self,k=slice(0,2)):
        self.table.cursor.execute('select %s,%s from %s where %s=%%s'
                                  %(self.table._attrSQL('target_id'),
                                    self.table._attrSQL('edge_id'),
                                    self.table.name,self.table._attrSQL('source_id')),
                                  (self.fromNode,))
        for row in self.table.cursor.fetchall():
            yield row[k]

class SQLGraphEdgeDescriptor(object):
    'provide an SQLEdges interface on demand'
    def __get__(self,obj,objtype):
        return SQLEdges(obj.name,obj.cursor,attrAlias=obj.getAttrAlias())

class SQLGraph(SQLTableMultiNoCache):
    '''provide a graph interface via a SQL table.  Key capabilities are:
       - setitem with an empty dictionary: a dummy operation
       - getitem with a key that exists: return a placeholder
       - setitem with non empty placeholder: again a dummy operation
       TABLE SCHEMA:
       create table mygraph (source_id int not null,target_id int not null,edge_id int,
              unique(source_id,target_id));
       '''
    _distinct_key='source_id'
    def __getitem__(self,k):
        return SQLEdgeDict(k,self)
    def __setitem__(self,k,v):
        pass
    def __contains__(self,k):
        return self.cursor.execute('select * from %s where %s=%%s'
                                   %(self.name,self._attrSQL('source_id')),(k,))>0
    def __invert__(self):
        'get an interface to the inverse graph mapping'
        try: # CACHED
            return self._inverse
        except AttributeError: # CONSTRUCT INTERFACE TO INVERSE MAPPING
            self._inverse=SQLGraph(self.name,self.cursor, # SWAP SOURCE & TARGET
                                   attrAlias=dict(source_id=self.data['target_id'],
                                                  target_id=self.data['source_id'],
                                                  edge_id=self.data['edge_id']))
            self._inverse._inverse=self
            return self._inverse
    def iteritems(self,myslice=slice(0,2)):
        for k in self:
            result=(k,SQLEdgeDict(k,self))
            yield result[myslice]
    keys=lambda self:[k for k in self]
    itervalues=lambda self:self.iteritems(1)
    values=lambda self:[k for k in self.iteritems(1)]
    items=lambda self:[k for k in self.iteritems()]
    edges=SQLGraphEdgeDescriptor()


class SQLEdgeDictClustered(dict):
    'simple cache for 2nd level dictionary of target_id:edge_id'
    def __init__(self,g,fromNode):
        self.g=g
        self.fromNode=fromNode
        dict.__init__(self)
    def __iadd__(self,l):
        for target_id,edge_id in l:
            dict.__setitem__(self,target_id,edge_id)
        return self # iadd MUST RETURN SELF!

class SQLEdgesClusteredDescr(object):
    def __get__(self,obj,objtype):
        e=SQLEdgesClustered(obj.table,obj.edge_id,obj.source_id,obj.target_id)
        for source_id,d in obj.d.iteritems(): # COPY EDGE CACHE
            e.load([(edge_id,source_id,target_id)
                    for (target_id,edge_id) in d.iteritems()])
        return e

class SQLGraphClustered(object):
    'SQL graph with clustered caching -- loads an entire cluster at a time'
    _edgeDictClass=SQLEdgeDictClustered
    def __init__(self,table,source_id='source_id',target_id='target_id',
                 edge_id='edge_id',clusterKey=None):
        import types
        if isinstance(table,types.StringType): # CREATE THE TABLE INTERFACE
            if clusterKey is None:
                raise ValueError('you must provide a clusterKey argument!')
            table=SQLTableClustered(table,clusterKey=clusterKey)
        self.table=table
        self.source_id=source_id
        self.target_id=target_id
        self.edge_id=edge_id
        self.d={}
    def __getstate__(self):
        return dict(table=self.table,source_id=self.source_id,
                    target_id=self.target_id,edge_id=self.edge_id,d={})
    def __getitem__(self,k):
        'get edgeDict for source node k, from cache or by loading its cluster'
        try: # GET DIRECTLY FROM CACHE
            return self.d[k]
        except KeyError:
            if hasattr(self,'_isLoaded'):
                raise # ENTIRE GRAPH LOADED, SO k REALLY NOT IN THIS GRAPH
        # HAVE TO LOAD THE ENTIRE CLUSTER CONTAINING THIS NODE
        self.table.cursor.execute('select t2.%s,t2.%s,t2.%s from %s t1,%s t2 where t1.%s=%%s and t1.%s=t2.%s group by t2.%s'
                                  %(self.source_id,self.target_id,
                                    self.edge_id,self.table.name,
                                    self.table.name,self.source_id,
                                    self.table.clusterKey,self.table.clusterKey,
                                    self.table.primary_key),(k,))
        self.load(self.table.cursor.fetchall()) # CACHE THIS CLUSTER
        return self.d[k] # RETURN EDGE DICT FOR THIS NODE
    def load(self,l=None):
        'load the specified rows (or all, if None provided) into local cache'
        if l is None:
            try: # IF ALREADY LOADED, NO NEED TO DO ANYTHING
                return self._isLoaded
            except AttributeError:
                pass
            self.table.cursor.execute('select %s,%s,%s from %s'
                                      %(self.source_id,self.target_id,
                                        self.edge_id,self.table.name))
            l=self.table.cursor.fetchall()
            self._isLoaded=True
            self.d.clear() # CLEAR OUR CACHE AS load() WILL REPLICATE EVERYTHING
        for source_id,target_id,edge_id in l: # SAVE TO OUR CACHE
            try:
                self.d[source_id]+=[(target_id,edge_id)]
            except KeyError:
                d=self._edgeDictClass(self,source_id)
                d+=[(target_id,edge_id)]
                self.d[source_id]=d
    def __invert__(self):
        'interface to reverse graph mapping'
        try:
            return self._inverse # INVERSE MAP ALREADY EXISTS
        except AttributeError:
            pass
        self._inverse=SQLGraphClustered(self.table,self.target_id,self.source_id,
                                        self.edge_id) # JUST SWAP TARGET & SOURCE
        self._inverse._inverse=self
        for source_id,d in self.d.iteritems(): # INVERT OUR CACHE
            self._inverse.load([(target_id,source_id,edge_id)
                                for (target_id,edge_id) in d.iteritems()])
        return self._inverse
    edges=SQLEdgesClusteredDescr() # CONSTRUCT EDGE INTERFACE ON DEMAND
    def __iter__(self): ################# ITERATORS
        'uses db select; does not force load'
        return iter(self.keys())
    def keys(self):
        'uses db select; does not force load'
        self.table.cursor.execute('select distinct(%s) from %s'
                                  %(self.source_id,self.table.name))
        return self.table.cursor.fetchall()
    def iteritems(self):
        'forces load of entire table into memory'
        self.load()
        return self.d.iteritems()
    def items(self): return [x for x in self.iteritems()]
    def itervalues(self):
        for t in self.iteritems():
            yield t[1]
    def values(self): return [t[1] for t in self.iteritems()]
    def __contains__(self,k):
        try:
            x=self[k]
            return True
        except KeyError:
            return False

class SQLEdgesClustered(SQLGraphClustered):
    'edges interface for SQLGraphClustered'
    class _edgeDictClass(list):
        def __init__(self,*l):
            list.__init__(self)
    def __iter__(self):
        self.load()
        for edge_id,l in self.d.iteritems():
            for source_id,target_id in l:
                yield source_id,target_id,edge_id


def describeDBTables(name,cursor,idDict):
    """
    Get table info about database <name> via <cursor>, and store primary keys
    in idDict, along with a list of the tables each key indexes.
    """
    cursor.execute('use %s' % name)
    cursor.execute('show tables')
    tables={}
    l=[c[0] for c in cursor.fetchall()]
    for t in l:
        tname=name+'.'+t
        o=SQLTable(tname,cursor)
        tables[tname]=o
        if o.primary_key:
            if o.primary_key not in idDict:
                idDict[o.primary_key]=[]
            idDict[o.primary_key].append(o) # KEEP LIST OF TABLES WITH THIS PRIMARY KEY
        for f in o.description:
            if f[-3:]=='_id' and f not in idDict:
                idDict[f]=[]
    return tables



def indexIDs(tables,idDict=None):
    "Get an index of primary keys in the <tables> dictionary."
    if idDict==None:
        idDict={}
    for o in tables.values():
        if o.primary_key:
            if o.primary_key not in idDict:
                idDict[o.primary_key]=[]
            idDict[o.primary_key].append(o) # KEEP LIST OF TABLES WITH THIS PRIMARY KEY
        for f in o.description:
            if f[-3:]=='_id' and f not in idDict:
                idDict[f]=[]
    return idDict
        


def suffixSubset(tables,suffix):
    "Filter table index for those matching a specific suffix"
    subset={}
    for name,t in tables.items():
        if name.endswith(suffix):
            subset[name]=t
    return subset


PRIMARY_KEY=1

def graphDBTables(tables,idDict):
    g=dictgraph()
    for t in tables.values():
        for f in t.description:
            if f==t.primary_key:
                edgeInfo=PRIMARY_KEY
            else:
                edgeInfo=None
            g.setEdge(f,t,edgeInfo)
            g.setEdge(t,f,edgeInfo)
    return g

SQLTypeTranslation= {types.StringType:'varchar(32)',
                     types.IntType:'int',
                     types.FloatType:'float'}

def createTableFromRepr(rows,tableName,cursor,typeTranslation=None,
                        optionalDict=None,indexDict=()):
    """Save rows into SQL tableName using cursor, with optional
       translations of columns to specific SQL types (specified
       by typeTranslation dict).
       - optionDict can specify columns that are allowed to be NULL.
       - indexDict can specify columns that must be indexed; columns
       whose names end in _id will be indexed by default.
       - rows must be an iterator which in turn returns dictionaries,
       each representing a tuple of values (indexed by their column
       names).
    """
    try:
        row=rows.next() # GET 1ST ROW TO EXTRACT COLUMN INFO
    except StopIteration:
        return # IF rows EMPTY, NO NEED TO SAVE ANYTHING, SO JUST RETURN
    try:
        createTableFromRow(cursor, tableName,row,typeTranslation,
                           optionalDict,indexDict)
    except:
        pass
    storeRow(cursor,tableName,row) # SAVE OUR FIRST ROW
    for row in rows: # NOW SAVE ALL THE ROWS
        storeRow(cursor,tableName,row)

def createTableFromRow(cursor, tableName, row,typeTranslation=None,
                        optionalDict=None,indexDict=()):
    create_defs=[]
    for col,val in row.items(): # PREPARE SQL TYPES FOR COLUMNS
        coltype=None
        if typeTranslation!=None and col in typeTranslation:
            coltype=typeTranslation[col] # USER-SUPPLIED TRANSLATION
        elif type(val) in SQLTypeTranslation:
            coltype=SQLTypeTranslation[type(val)]
        else: # SEARCH FOR A COMPATIBLE TYPE
            for t in SQLTypeTranslation:
                if isinstance(val,t):
                    coltype=SQLTypeTranslation[t]
                    break
        if coltype==None:
            raise TypeError("Don't know SQL type to use for %s" % col)
        create_def='%s %s' %(col,coltype)
        if optionalDict==None or col not in optionalDict:
            create_def+=' not null'
        create_defs.append(create_def)
    for col in row: # CREATE INDEXES FOR ID COLUMNS
        if col[-3:]=='_id' or col in indexDict:
            create_defs.append('index(%s)' % col)
    cmd='create table if not exists %s (%s)' % (tableName,','.join(create_defs))
    cursor.execute(cmd) # CREATE THE TABLE IN THE DATABASE


def storeRow(cursor, tableName, row):
    row_format=','.join(len(row)*['%s'])
    cmd='insert into %s values (%s)' % (tableName,row_format)
    cursor.execute(cmd,tuple(row.values()))

def storeRowDelayed(cursor, tableName, row):
    row_format=','.join(len(row)*['%s'])
    cmd='insert delayed into %s values (%s)' % (tableName,row_format)
    cursor.execute(cmd,tuple(row.values()))


class TableGroup(dict):
    'provide attribute access to dbname qualified tablenames'
    def __init__(self,db='test',suffix=None,**kw):
        dict.__init__(self)
        self.db=db
        if suffix is not None:
            self.suffix=suffix
        for k,v in kw.items():
            if v is not None and '.' not in v:
                v=self.db+'.'+v  # ADD DATABASE NAME AS PREFIX
            self[k]=v
    def __getattr__(self,k):
        return self[k]
