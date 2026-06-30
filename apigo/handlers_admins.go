package main

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"

	"github.com/jackc/pgx/v5"
)

func (a *App) loadAdmin(ctx context.Context, id int64) (*adminRow, error) {
	// Note: unlike getAdminByID this does NOT filter on disabled_at, so disabled
	// admins are still manageable (mirrors get_scoped(Admin, ...)).
	row := a.db.QueryRow(ctx, `SELECT `+adminCols+` FROM admins WHERE id=$1`, id)
	adm, err := scanAdmin(row)
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return nil, nil
		}
		return nil, err
	}
	return adm, nil
}

func (a *App) countActiveSuperAdmins(ctx context.Context) (int64, error) {
	var n int64
	err := a.db.QueryRow(ctx,
		`SELECT count(id) FROM admins WHERE role='super_admin' AND disabled_at IS NULL`).Scan(&n)
	return n, err
}

func (a *App) handleListAdmins(w http.ResponseWriter, r *http.Request) {
	tid := tenantID(r)
	q := `SELECT ` + adminCols + ` FROM admins`
	var args []any
	if a.scoped(tid) {
		q += ` WHERE tenant_id=$1`
		args = append(args, *tid)
	}
	q += ` ORDER BY username`
	rows, err := a.db.Query(r.Context(), q, args...)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "db error")
		return
	}
	defer rows.Close()
	out := []AdminOut{}
	for rows.Next() {
		adm, err := scanAdmin(rows)
		if err != nil {
			writeError(w, http.StatusInternalServerError, "db error")
			return
		}
		out = append(out, adm.DTO())
	}
	writeJSON(w, http.StatusOK, out)
}

func (a *App) handleCreateAdmin(w http.ResponseWriter, r *http.Request) {
	var in struct {
		Username string  `json:"username"`
		Password string  `json:"password"`
		Role     *string `json:"role"`
		TgUserID *int64  `json:"tg_user_id"`
		TenantID *int64  `json:"tenant_id"`
	}
	if err := decodeJSON(r, &in); err != nil || len(in.Username) < 3 || len(in.Password) < 8 {
		writeError(w, http.StatusUnprocessableEntity, "username (>=3) and password (>=8) are required")
		return
	}
	role := string(RoleEditor)
	if in.Role != nil && *in.Role != "" {
		if !validRole(*in.Role) {
			writeError(w, http.StatusUnprocessableEntity, "invalid role")
			return
		}
		role = *in.Role
	}
	hash, err := hashPassword(in.Password)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "hash error")
		return
	}
	tenantVal := in.TenantID
	if tenantVal == nil {
		tenantVal = a.stampTenant(r)
	}
	row := a.db.QueryRow(r.Context(),
		`INSERT INTO admins(username,password_hash,role,tg_user_id,tenant_id)
		 VALUES($1,$2,$3,$4,$5) RETURNING `+adminCols,
		in.Username, hash, role, in.TgUserID, tenantVal)
	adm, err := scanAdmin(row)
	if err != nil {
		if isUniqueViolation(err) {
			writeError(w, http.StatusConflict, "username already exists")
			return
		}
		writeError(w, http.StatusInternalServerError, "db error")
		return
	}
	writeJSON(w, http.StatusCreated, adm.DTO())
}

func (a *App) handleUpdateAdmin(w http.ResponseWriter, r *http.Request) {
	id, ok := urlInt64(r, "adminID")
	if !ok {
		writeError(w, http.StatusNotFound, "admin not found")
		return
	}
	tid := tenantID(r)
	adm, err := a.loadAdmin(r.Context(), id)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "db error")
		return
	}
	if adm == nil || !a.tenantOwned(tid, adm.TenantID) {
		writeError(w, http.StatusNotFound, "admin not found")
		return
	}
	body, err := decodePatchBody(r)
	if err != nil {
		writeError(w, http.StatusUnprocessableEntity, "invalid body")
		return
	}

	b := &setBuilder{}

	if raw, ok := presentNotNull(body, "password"); ok {
		var pw string
		if err := json.Unmarshal(raw, &pw); err != nil {
			writeError(w, http.StatusUnprocessableEntity, "invalid password")
			return
		}
		hash, err := hashPassword(pw)
		if err != nil {
			writeError(w, http.StatusInternalServerError, "hash error")
			return
		}
		b.add("password_hash", hash)
	}

	if raw, ok := presentNotNull(body, "role"); ok {
		var role string
		if err := json.Unmarshal(raw, &role); err != nil || !validRole(role) {
			writeError(w, http.StatusUnprocessableEntity, "invalid role")
			return
		}
		if role != adm.Role {
			if adm.Role == string(RoleSuperAdmin) && role != string(RoleSuperAdmin) {
				n, err := a.countActiveSuperAdmins(r.Context())
				if err != nil {
					writeError(w, http.StatusInternalServerError, "db error")
					return
				}
				if n <= 1 {
					writeError(w, http.StatusBadRequest, "cannot demote the last super-admin")
					return
				}
			}
			b.add("role", role)
		}
	}

	if raw, ok := presentNotNull(body, "disabled"); ok {
		var disabled bool
		if err := json.Unmarshal(raw, &disabled); err != nil {
			writeError(w, http.StatusUnprocessableEntity, "invalid disabled")
			return
		}
		if disabled && adm.Role == string(RoleSuperAdmin) && adm.DisabledAt == nil {
			n, err := a.countActiveSuperAdmins(r.Context())
			if err != nil {
				writeError(w, http.StatusInternalServerError, "db error")
				return
			}
			if n <= 1 {
				writeError(w, http.StatusBadRequest, "cannot disable the last active super-admin")
				return
			}
		}
		if disabled {
			b.addRaw("disabled_at=now()")
		} else {
			b.addRaw("disabled_at=NULL")
		}
	}

	// tg_user_id is presence-based (explicit null clears it).
	if raw, ok := body["tg_user_id"]; ok {
		var v *int64
		if err := json.Unmarshal(raw, &v); err != nil {
			writeError(w, http.StatusUnprocessableEntity, "invalid tg_user_id")
			return
		}
		b.add("tg_user_id", v)
	}

	if b.empty() {
		writeJSON(w, http.StatusOK, adm.DTO())
		return
	}
	q := `UPDATE admins SET ` + b.clause() + fmt.Sprintf(" WHERE id=$%d RETURNING ", len(b.args)+1) + adminCols
	b.args = append(b.args, id)
	updated, err := scanAdmin(a.db.QueryRow(r.Context(), q, b.args...))
	if err != nil {
		writeError(w, http.StatusInternalServerError, "db error")
		return
	}
	writeJSON(w, http.StatusOK, updated.DTO())
}
