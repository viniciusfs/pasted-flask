drop table if exists pastes;
create table pastes (
  id integer primary key autoincrement,
  code string not null,
  md5 string not null,
  viewed_at string,
  parent string
);
