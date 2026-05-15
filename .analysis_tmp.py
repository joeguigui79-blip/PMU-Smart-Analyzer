import sqlite3, json, math, statistics
from collections import defaultdict, Counter
from datetime import datetime

DB='pmu_analyzer.db'
conn=sqlite3.connect(DB)
conn.row_factory=sqlite3.Row
cur=conn.cursor()

rows=cur.execute('''
select r.date_str, r.hippodrome_libelle as hippodrome, c.id as course_id, c.discipline, c.specialite, c.nombre_partants,
       c.distance, c.terrain, c.statut_resultat, c.paris_disponibles,
       p.id as participant_id, p.num_pmu, p.nom, p.cote_actuelle, p.cote_initiale,
       p.score_global, p.score_global_auto, p.score_global_expert, p.score_sans_cote,
       p.score_forme, p.score_cote, p.score_jockey, p.score_entraineur, p.score_distance, p.score_terrain,
       p.score_repos, p.score_partants, p.score_hippodrome, p.score_poids, p.score_corde, p.score_regularite, p.score_recence,
       p.score_gains, p.score_age, p.is_value_bet, p.position_arrivee
from participants p
join courses c on c.id = p.course_id
join reunions r on r.id = c.reunion_id
where c.statut_resultat = 'TERMINE' and r.date_str >= '08052026' and p.position_arrivee is not null
order by r.date_str, c.id, p.score_global desc
''').fetchall()

def norm_disc(d):
    d=(d or '').upper().strip()
    if d in ('ATTELE','TROT_ATTELE'): return 'TROT_ATTELE'
    if d in ('MONTE','TROT_MONTE'): return 'TROT_MONTE'
    if d in ('HAIE','HAIES','OBSTACLE'): return 'HAIE'
    if d in ('STEEPLE','STEEPLECHASE'): return 'STEEPLE'
    if d=='CROSS': return 'CROSS'
    return 'PLAT'

def spearman(xs, ys):
    n=len(xs)
    if n < 3:
        return None
    def ranks(vals):
        sorted_indexed=sorted(enumerate(vals), key=lambda t:t[1])
        out=[0.0]*n
        i=0
        while i<n:
            j=i
            while j+1<n and sorted_indexed[j+1][1]==sorted_indexed[i][1]:
                j+=1
            avg=(i+j)/2+1
            for k in range(i,j+1):
                out[sorted_indexed[k][0]]=avg
            i=j+1
        return out
    rx=ranks(xs); ry=ranks(ys)
    mx=sum(rx)/n; my=sum(ry)/n
    num=sum((rx[i]-mx)*(ry[i]-my) for i in range(n))
    denx=math.sqrt(sum((rx[i]-mx)**2 for i in range(n)))
    deny=math.sqrt(sum((ry[i]-my)**2 for i in range(n)))
    if denx==0 or deny==0:
        return 0.0
    return num/(denx*deny)

courses={}
for r in rows:
    cid=r['course_id']
    courses.setdefault(cid, {'date_str':r['date_str'], 'hippodrome':r['hippodrome'], 'discipline':norm_disc(r['discipline']), 'specialite':r['specialite'], 'nombre_partants':r['nombre_partants'], 'distance':r['distance'], 'terrain':r['terrain'], 'participants':[]})
    courses[cid]['participants'].append(dict(r))

criterion_fields={
    'forme_recente':'score_forme',
    'value_cote':'score_cote',
    'jockey':'score_jockey',
    'entraineur':'score_entraineur',
    'distance':'score_distance',
    'terrain':'score_terrain',
    'repos':'score_repos',
    'partants':'score_partants',
    'hippodrome':'score_hippodrome',
    'poids':'score_poids',
    'corde':'score_corde',
    'regularite':'score_regularite',
    'recence':'score_recence',
    'gains':'score_gains',
    'age':'score_age',
}

disc_stats=defaultdict(lambda: {'courses':0,'top1_win':0,'top1_top3':0,'top3_all_top3':0,'top5_all_top5':0,'rank_corrs':[],'fav_win':0,'fav_top3':0,'fav_count':0,'vb_count':0,'vb_top3':0,'vb_win':0,'vb_profitable_win_only':0.0,'vb_stakes':0.0,'low_odds_count':0,'low_odds_win':0,'mid_odds_count':0,'mid_odds_win':0,'high_odds_count':0,'high_odds_win':0,'outsider_top1_count':0,'outsider_top1_win':0,'by_partants_small':{'count':0,'win':0},'by_partants_mid':{'count':0,'win':0},'by_partants_large':{'count':0,'win':0},'hippos':Counter()})
criterion_stats=defaultdict(lambda: defaultdict(lambda: {'wins':0,'courses':0,'corrs':[]}))
overall={'courses':0,'top1_win':0,'top1_top3':0,'score_global_corrs':[],'score_auto_corrs':[],'score_sans_corrs':[]}

for cid, course in courses.items():
    ps=course['participants']
    disc=course['discipline']
    ds=disc_stats[disc]
    ds['courses']+=1
    overall['courses']+=1
    ds['hippos'][course['hippodrome']]+=1

    ranked=sorted(ps, key=lambda p:(p['score_global'] or 0), reverse=True)
    ranked_auto=sorted(ps, key=lambda p:(p['score_global_auto'] or 0), reverse=True)
    ranked_sans=sorted(ps, key=lambda p:(p['score_sans_cote'] or 0), reverse=True)
    top1=ranked[0]
    if top1['position_arrivee']==1:
        ds['top1_win']+=1; overall['top1_win']+=1
    if top1['position_arrivee']<=3:
        ds['top1_top3']+=1; overall['top1_top3']+=1

    pred_top3={p['num_pmu'] for p in ranked[:3]}
    real_top3={p['num_pmu'] for p in ps if p['position_arrivee']<=3}
    if len(pred_top3)==3 and pred_top3==real_top3:
        ds['top3_all_top3']+=1
    pred_top5={p['num_pmu'] for p in ranked[:5]}
    real_top5={p['num_pmu'] for p in ps if p['position_arrivee']<=5}
    if len(pred_top5)==5 and pred_top5==real_top5:
        ds['top5_all_top5']+=1

    favs=[p for p in ps if p['cote_actuelle'] is not None and p['cote_actuelle']>0]
    if favs:
        fav=min(favs, key=lambda p:p['cote_actuelle'])
        ds['fav_count']+=1
        if fav['position_arrivee']==1: ds['fav_win']+=1
        if fav['position_arrivee']<=3: ds['fav_top3']+=1

    if top1.get('cote_actuelle') is not None:
        c=top1['cote_actuelle']
        if c<=3:
            ds['low_odds_count']+=1
            if top1['position_arrivee']==1: ds['low_odds_win']+=1
        elif c<=8:
            ds['mid_odds_count']+=1
            if top1['position_arrivee']==1: ds['mid_odds_win']+=1
        else:
            ds['high_odds_count']+=1
            if top1['position_arrivee']==1: ds['high_odds_win']+=1
        if c>8:
            ds['outsider_top1_count']+=1
            if top1['position_arrivee']==1: ds['outsider_top1_win']+=1

    np=course['nombre_partants'] or len(ps)
    bucket='by_partants_small' if np<=10 else ('by_partants_mid' if np<=13 else 'by_partants_large')
    ds[bucket]['count']+=1
    if top1['position_arrivee']==1: ds[bucket]['win']+=1

    xs=[p['score_global'] or 0 for p in ps]; ys=[-p['position_arrivee'] for p in ps]
    corr=spearman(xs,ys)
    if corr is not None:
        ds['rank_corrs'].append(corr); overall['score_global_corrs'].append(corr)
    xs=[p['score_global_auto'] or 0 for p in ps]; corr=spearman(xs,ys)
    if corr is not None: overall['score_auto_corrs'].append(corr)
    xs=[p['score_sans_cote'] or 0 for p in ps]; corr=spearman(xs,ys)
    if corr is not None: overall['score_sans_corrs'].append(corr)

    for crit, field in criterion_fields.items():
        vals=[p[field] if p[field] is not None else 50.0 for p in ps]
        corr=spearman(vals, ys)
        if corr is not None:
            criterion_stats[disc][crit]['corrs'].append(corr)
        best=max(ps, key=lambda p:(p[field] if p[field] is not None else -9999))
        criterion_stats[disc][crit]['courses']+=1
        if best['position_arrivee']==1:
            criterion_stats[disc][crit]['wins']+=1

    for p in ps:
        if p['is_value_bet']:
            ds['vb_count']+=1
            ds['vb_stakes']+=1.0
            c=p['cote_actuelle'] or p['cote_initiale']
            if p['position_arrivee']<=3: ds['vb_top3']+=1
            if p['position_arrivee']==1:
                ds['vb_win']+=1
                if c and c>0:
                    ds['vb_profitable_win_only'] += c

summary={
    'date_range': [min(c['date_str'] for c in courses.values()) if courses else None, max(c['date_str'] for c in courses.values()) if courses else None],
    'courses_total': len(courses),
    'participants_total': len(rows),
    'overall': {
        'top1_win_rate': round(overall['top1_win']/overall['courses']*100,1) if overall['courses'] else None,
        'top1_top3_rate': round(overall['top1_top3']/overall['courses']*100,1) if overall['courses'] else None,
        'avg_spearman_score_global': round(sum(overall['score_global_corrs'])/len(overall['score_global_corrs']),4) if overall['score_global_corrs'] else None,
        'avg_spearman_score_auto': round(sum(overall['score_auto_corrs'])/len(overall['score_auto_corrs']),4) if overall['score_auto_corrs'] else None,
        'avg_spearman_score_sans_cote': round(sum(overall['score_sans_corrs'])/len(overall['score_sans_corrs']),4) if overall['score_sans_corrs'] else None,
    },
    'by_discipline': {},
    'criterion_summary': {}
}
for disc, ds in sorted(disc_stats.items()):
    summary['by_discipline'][disc]={
        'courses': ds['courses'],
        'top1_win_rate': round(ds['top1_win']/ds['courses']*100,1) if ds['courses'] else None,
        'top1_top3_rate': round(ds['top1_top3']/ds['courses']*100,1) if ds['courses'] else None,
        'top3_exact_set_rate': round(ds['top3_all_top3']/ds['courses']*100,1) if ds['courses'] else None,
        'top5_exact_set_rate': round(ds['top5_all_top5']/ds['courses']*100,1) if ds['courses'] else None,
        'avg_score_global_spearman': round(sum(ds['rank_corrs'])/len(ds['rank_corrs']),4) if ds['rank_corrs'] else None,
        'favorite_win_rate': round(ds['fav_win']/ds['fav_count']*100,1) if ds['fav_count'] else None,
        'favorite_top3_rate': round(ds['fav_top3']/ds['fav_count']*100,1) if ds['fav_count'] else None,
        'value_bets': {
            'count': ds['vb_count'],
            'top3_rate': round(ds['vb_top3']/ds['vb_count']*100,1) if ds['vb_count'] else None,
            'win_rate': round(ds['vb_win']/ds['vb_count']*100,1) if ds['vb_count'] else None,
            'roi_win_only': round((ds['vb_profitable_win_only']-ds['vb_stakes'])/ds['vb_stakes']*100,1) if ds['vb_stakes'] else None,
        },
        'top1_by_odds': {
            'low_<=3': round(ds['low_odds_win']/ds['low_odds_count']*100,1) if ds['low_odds_count'] else None,
            'mid_3_8': round(ds['mid_odds_win']/ds['mid_odds_count']*100,1) if ds['mid_odds_count'] else None,
            'high_>8': round(ds['high_odds_win']/ds['high_odds_count']*100,1) if ds['high_odds_count'] else None,
            'outsider_top1_share': round(ds['outsider_top1_count']/ds['courses']*100,1) if ds['courses'] else None,
        },
        'top1_by_field_size': {
            'small_<=10': round(ds['by_partants_small']['win']/ds['by_partants_small']['count']*100,1) if ds['by_partants_small']['count'] else None,
            'mid_11_13': round(ds['by_partants_mid']['win']/ds['by_partants_mid']['count']*100,1) if ds['by_partants_mid']['count'] else None,
            'large_14+': round(ds['by_partants_large']['win']/ds['by_partants_large']['count']*100,1) if ds['by_partants_large']['count'] else None,
        },
        'top_hippodromes': ds['hippos'].most_common(5),
    }

for disc, stats in sorted(criterion_stats.items()):
    summary['criterion_summary'][disc]={}
    for crit, st in sorted(stats.items()):
        avg_corr = (sum(st['corrs'])/len(st['corrs'])) if st['corrs'] else None
        summary['criterion_summary'][disc][crit]={
            'best_score_win_rate': round(st['wins']/st['courses']*100,1) if st['courses'] else None,
            'avg_spearman': round(avg_corr,4) if avg_corr is not None else None,
            'courses': st['courses'],
        }

print(json.dumps(summary, ensure_ascii=False, indent=2))
