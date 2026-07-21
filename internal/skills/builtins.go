// 来源：公众号@小林coding
// 后端八股网站：xiaolincoding.com
// Agent网站：xiaolinnote.com
// 简历模版：jianli.xiaolinnote.com

package skills

// LoadBuiltins returns embedded skills compiled into the binary.
// Currently empty — all skills are loaded from disk at runtime
// (user-level ~/.mewcode/skills/ or project-level .mewcode/skills/).
func LoadBuiltins() []*Skill {
	return nil
}
